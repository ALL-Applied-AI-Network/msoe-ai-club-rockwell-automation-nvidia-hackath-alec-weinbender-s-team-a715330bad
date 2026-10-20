"""GPU targets the sim server runs on: the instances a backend offers, starting and stopping one, checking and starting
the sim server on it, and the command that forwards its sim port to this machine. Mock (made-up instances, the default),
Brev, and the MSOE GB10. Brev instances are created in its console; the app only starts, watches and stops them. The GB10
is always on and shared with other teams (always_on): there's nothing to start or stop, so the app only starts the sim
server there if it isn't running, and connects to it.

Brev documents no REST API, so BrevCompute drives its CLI: `brev ls --json`, `brev start`, `brev stop`, `brev exec` and
`brev port-forward`. On Windows the CLI only runs inside WSL (COMPUTE_BREV_WSL names the distro). `wsl -- brev ...` won't
do: it runs the command line through a shell that drops the quoting, so `brev exec box "a | b"` would pipe on this
machine. The CLI goes through `wsl -e bash -lc 'exec brev "$@"'` instead, which hands each argument over exactly, from a
login shell (so ~/.local/bin, where the installer puts brev, is on PATH). Scripts sent with `brev exec` travel
base64-encoded on top, so no quoting has to survive the remote shell either.

Gb10Compute runs everything with the system ssh (on Windows the built-in OpenSSH, no WSL), key auth only (BatchMode: it
never prompts), on the MSOE VPN. Each script goes on stdin to `bash -s`, as bytes with LF line ends, so nothing is quoted
twice and Windows can't add a CR.

The sim server is set up on a target once, by hand (docs/notes/gpu-test-plan.md: the repo, sim_server installed into
Isaac's Python). These clients only start it.
"""

import base64
import json
import logging
import os
import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

from api.config import ComputeConfig
from api.models.compute import ComputeBackend, ComputeInstance, InstanceState

logger = logging.getLogger(__name__)

# ready: answering. not_running: nothing to say it was started. host_not_ready: the instance's container isn't up yet.
# Only targets that track the server's process report the rest: starting (alive, not answering yet), exited (it was
# started and its process is gone), stuck (alive, but Isaac Sim never finished starting).
SimState = Literal["ready", "not_running", "host_not_ready", "starting", "exited", "stuck"]
CLI_TIMEOUT_S = 120  # one Brev CLI call: ls, start, stop or exec
SSH_TIMEOUT_S = 60  # one script on the GB10
# Isaac Sim fails to start on the GB10 about 1 time in 4: it hangs before Kit logs anything, or segfaults in the Vulkan
# driver within seconds (docs/experiments/2026-10-20-gb10-stages-4-6.md). A start whose log has no KIT_STARTED line after
# KIT_START_TIMEOUT_S is stuck. A good start logs it within seconds; the slow part of a cold start (the shader cache,
# minutes) comes after it.
KIT_STARTED = "Simulation App Startup Complete"
KIT_START_TIMEOUT_S = 90
BREV_STATES: dict[str, InstanceState] = {
    "RUNNING": "running",
    "STARTING": "starting",
    "DEPLOYING": "starting",
    "STOPPING": "stopping",
    "STOPPED": "stopped",
}
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new")
# ssh's own failures (exit code 255), as what to do about them; checked in order.
SSH_FAILURES = (
    (re.compile(r"host key verification failed|remote host identification has changed", re.I), "host_key"),
    (re.compile(r"permission denied", re.I), "permission"),
    (re.compile(r"could not resolve|timed out|network is unreachable|no route to host|connection refused", re.I), "unreachable"),
)
# No console window for a child process: the session process is detached, so on Windows every call would open one.
NO_WINDOW: dict[str, Any] = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# The GB10 scripts' bash function: what the process in runs/sim_server.pid (run from the repo) is doing. none: no pid
# file. exited. stuck: alive KIT_START_TIMEOUT_S on, and its log (wherever its stdout goes, so a teammate's hand-started
# server counts too) has no KIT_STARTED line; a log it can't read is never called stuck. starting: alive otherwise.
_SIM_PROCESS = (
    "sim_process() {\n"
    "  local pid log age\n"
    "  pid=$(cat runs/sim_server.pid 2>/dev/null)\n"
    '  if [ -z "$pid" ]; then echo none; return; fi\n'
    '  if ! kill -0 "$pid" 2>/dev/null; then echo exited; return; fi\n'
    '  log=$(readlink "/proc/$pid/fd/1" 2>/dev/null); age=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d " ")\n'
    f'  if [ -f "$log" ] && [ "${{age:-0}}" -ge {KIT_START_TIMEOUT_S} ] && ! grep -q "{KIT_STARTED}" "$log"; then\n'
    "    echo stuck; return\n"
    "  fi\n"
    "  echo starting\n"
    "}"
)


class ComputeError(RuntimeError):
    """The provider couldn't do what was asked, or couldn't be reached. The message says why, for the GPU panel."""


class ComputeClient(Protocol):
    backend: ComputeBackend
    always_on: bool  # nothing to start or stop (the GB10): sessions connect and disconnect

    def instances(self) -> list[ComputeInstance]:
        """Every target this backend offers, whatever its state."""
        ...

    def start(self, name: str) -> None:
        """Ask the provider to start a stopped instance. Returns before it's running: watch instances()."""
        ...

    def stop(self, name: str) -> None:
        """Ask the provider to stop the instance. Returns before it has stopped. Never called for an always-on target."""
        ...

    def sim_state(self, name: str) -> SimState:
        """On the target itself, not through the forward: "ready" if the sim server answers, "host_not_ready" while
        what it runs in (the Isaac container) isn't up yet, else "not_running"."""
        ...

    def start_sim(self, name: str) -> None:
        """Start the sim server on the target, in the background. Isaac Sim takes about a minute to load."""
        ...

    def forward_command(self, name: str, local_port: int) -> list[str] | None:
        """The long-running command that forwards the target's sim port to local_port on this machine, or None when
        there's nothing to forward (the mock)."""
        ...

    def close(self) -> None: ...


class MockCompute:
    """Made-up instances, for building and testing the app offline. Their states live in a small JSON file, so the API
    and the session process see the same ones. Its sim is the mock sim, so there's nothing to start or forward."""

    backend: ComputeBackend = "mock"
    always_on = False
    INSTANCES = {"mock-rtx-pro-4500": ("RTX PRO 4500", "g7.2xlarge"), "mock-l40s": ("L40S", "g6e.xlarge")}

    def __init__(self, state_path: Path):
        self.state_path = state_path

    def instances(self) -> list[ComputeInstance]:
        states = self._states()
        return [
            ComputeInstance(
                backend=self.backend,
                name=name,
                id=f"mock-{i}",
                status=states[name].upper(),
                state=states[name],
                gpu=gpu,
                instance_type=kind,
            )
            for i, (name, (gpu, kind)) in enumerate(self.INSTANCES.items())
        ]

    def start(self, name: str) -> None:
        self._set(name, "running")

    def stop(self, name: str) -> None:
        self._set(name, "stopped")

    def sim_state(self, name: str) -> SimState:
        return "ready" if self._states()[self._known(name)] == "running" else "host_not_ready"

    def start_sim(self, name: str) -> None:
        self._known(name)

    def forward_command(self, name: str, local_port: int) -> list[str] | None:
        return None

    def close(self) -> None:
        pass

    def _states(self) -> dict[str, InstanceState]:
        try:
            saved = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            saved = {}
        return {name: saved.get(name, "stopped") for name in self.INSTANCES}

    def _set(self, name: str, state: InstanceState) -> None:
        states = self._states()
        states[self._known(name)] = state
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(states))

    def _known(self, name: str) -> str:
        if name not in self.INSTANCES:
            raise ComputeError(f"the mock has no instance {name!r}")
        return name


class BrevCompute:
    """Instances in the team's Brev org, through the brev CLI. Holds plain attributes only."""

    backend: ComputeBackend = "brev"
    always_on = False

    def __init__(self, config: ComputeConfig, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.config = config
        self.cli = brev_command(config)
        self._run = run
        self._logged_in = config.brev_token is None  # without a token, the CLI's own login (brev login) is used

    def instances(self) -> list[ComputeInstance]:
        out = self._brev("ls", "--json")
        try:
            body = json.loads(out[out.index("{") :])
            return [_brev_instance(w) for w in body["workspaces"] or []]
        except (ValueError, KeyError, TypeError) as e:
            raise ComputeError("brev ls --json didn't answer with the instance list") from e

    def start(self, name: str) -> None:
        self._brev("start", name, "--detached")

    def stop(self, name: str) -> None:
        self._brev("stop", name)

    def sim_state(self, name: str) -> SimState:
        out = self._exec(name, self.sim_state_script())
        match = re.search(r"SIM_STATE=(\w+)", out)
        if match is None or match[1] not in get_args(SimState):
            raise ComputeError(f"couldn't read the sim server's state on {name}: {_last_line(out) or 'no output'}")
        return match[1]

    def start_sim(self, name: str) -> None:
        self._exec(name, self.start_sim_script())

    def forward_command(self, name: str, local_port: int) -> list[str] | None:
        return [*self.cli, "port-forward", name, "-p", f"{local_port}:{self.config.sim_port}"]

    def close(self) -> None:
        pass

    def sim_state_script(self) -> str:
        """Prints SIM_STATE=host_not_ready, ready or not_running. The launchable's container uses the host network, so
        the server is on the VM's localhost either way."""
        container, port = self.config.sim_container, self.config.sim_port
        lines = []
        if container:
            lines.append(
                f"docker ps --filter name=^{container}$ --format '{{{{.Status}}}}' | grep -q '^Up' "
                "|| { echo SIM_STATE=host_not_ready; exit 0; }"
            )
        lines.append(
            f'curl -s -m 5 http://127.0.0.1:{port}/health | grep -q \'"status":"ok"\' && echo SIM_STATE=ready || echo SIM_STATE=not_running'
        )
        return "\n".join(lines) + "\n"

    def start_sim_script(self) -> str:
        """Starts python -m sim_server in the background, its log appended to runs/sim_server.log in the repo."""
        c = self.config
        serve = f"{shlex.quote(c.isaac_python)} -m sim_server --port {c.sim_port} {c.sim_args}".strip()
        command = f"cd {shlex.quote(c.sim_dir)} && mkdir -p runs && exec {serve} >> runs/sim_server.log 2>&1"
        if c.sim_container:
            return f"docker exec -d {shlex.quote(c.sim_container)} bash -lc {shlex.quote(command)}\n"
        return f"nohup bash -lc {shlex.quote(command)} > /dev/null 2>&1 &\n"

    def _exec(self, name: str, script: str) -> str:
        encoded = base64.b64encode(script.encode()).decode()
        return self._brev("exec", name, f"echo {encoded} | base64 -d | bash")

    def _brev(self, *args: str) -> str:
        if not self._logged_in:
            self._call([*self.cli, "login", "--token", self.config.brev_token.get_secret_value()], "brev login")
            self._logged_in = True
        return self._call([*self.cli, *args], f"brev {args[0]}")

    def _call(self, command: list[str], what: str) -> str:
        """Run the CLI and return its output. The command is never logged: a login carries the token."""
        try:
            done = self._run(
                command,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CLI_TIMEOUT_S,
                **NO_WINDOW,
            )
        except FileNotFoundError:
            raise ComputeError(
                f"can't run the Brev CLI ({self.cli[0]}): install it (SETUP.md), or set COMPUTE_BREV_CLI or COMPUTE_BREV_WSL"
            ) from None
        except subprocess.TimeoutExpired:
            raise ComputeError(f"{what} didn't finish within {CLI_TIMEOUT_S} s") from None
        if done.returncode != 0:
            detail = _last_line(done.stderr) or _last_line(done.stdout) or f"exit code {done.returncode}"
            raise ComputeError(f"{what} failed: {detail}")
        return done.stdout or ""


class Gb10Compute:
    """The MSOE GB10 (spark1.ai.msoe.edu): always on and shared with other teams, so it's one target that's always
    running. A session starts our sim server there if it isn't running (one per team account: a lock and a pid file stop
    two teammates starting two), forwards its port with ssh -L, and on disconnect closes only the forward, leaving the
    server running for teammates. The app never stops the machine or the server."""

    backend: ComputeBackend = "gb10"
    always_on = True

    def __init__(self, config: ComputeConfig, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self.config = config
        self.ssh = shlex.split(config.ssh)
        self.target = f"{config.gb10_user}@{config.gb10_host}"
        self.name = config.gb10_host.split(".")[0]  # spark1
        self._run = run

    def instances(self) -> list[ComputeInstance]:
        """The GB10, with its GPU load from nvidia-smi: other_gpu_processes counts every GPU process but our sim server
        (another team's, or a teammate's run), and the status is AVAILABLE when there are none, else BUSY."""
        out = self._script(self.probe_script(), "checking the GB10")
        match = re.search(r"GPU_PROCESSES=(\d+) SIM_SERVER=([01])", out)
        if match is None:
            raise ComputeError(f"couldn't read the GB10's GPU load: {_last_line(out) or 'no output'}")
        others = int(match[1]) - int(match[2])
        return [
            ComputeInstance(
                backend=self.backend,
                name=self.name,
                id=self.config.gb10_host,
                status="AVAILABLE" if others == 0 else "BUSY",
                state="running",
                gpu="NVIDIA GB10",
                instance_type="DGX Spark",
                always_on=True,
                other_gpu_processes=others,
            )
        ]

    def start(self, name: str) -> None:
        """Nothing to start: the GB10 is always on."""

    def stop(self, name: str) -> None:
        """Never stopped from here: other teams use the machine."""

    def sim_state(self, name: str) -> SimState:
        out = self._script(self.sim_state_script(), "checking the sim server on the GB10")
        match = re.search(r"SIM_STATE=(\w+)", out)
        state = match[1] if match else None
        if state == "not_set_up":
            raise ComputeError(
                "GB10 not set up: the repo or Isaac Sim's python.sh is missing there "
                f"({self.config.gb10_sim_dir}, {self.config.gb10_isaac_python}); see the runbook, docs/notes/gpu-test-plan.md"
            )
        if state == "port_taken":
            raise ComputeError(
                f"port {self.config.gb10_sim_port} on the GB10 is held by another account: set COMPUTE_GB10_SIM_PORT to a free one"
            )
        if state not in get_args(SimState):
            raise ComputeError(f"couldn't read the sim server's state on the GB10: {_last_line(out) or 'no output'}")
        return state

    def start_sim(self, name: str) -> None:
        out = self._script(self.start_sim_script(), "starting the sim server on the GB10")
        if "SIM_START=locked" in out:
            raise ComputeError("a teammate is starting the GB10's sim server right now: try again in a minute")
        if "SIM_START=" not in out:
            raise ComputeError(f"couldn't start the sim server on the GB10: {_last_line(out) or 'no output'}")

    def forward_command(self, name: str, local_port: int) -> list[str] | None:
        port = self.config.gb10_sim_port
        return [
            *self.ssh,
            "-N",
            *SSH_OPTIONS,
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-L",
            f"127.0.0.1:{local_port}:127.0.0.1:{port}",
            self.target,
        ]

    def close(self) -> None:
        pass

    def probe_script(self) -> str:
        """Prints GPU_PROCESSES=n SIM_SERVER=0|1: compute processes on the GPU, any account's, and whether one of them is
        our sim server (the process listening on its port; ss shows pids only for this account's processes)."""
        return "\n".join(
            [
                f"PORT={self.config.gb10_sim_port}",
                "sim=$(ss -ltnpH \"sport = :$PORT\" 2>/dev/null | grep -o 'pid=[0-9]*' | head -n 1 | cut -d= -f2)",
                "n=0; ours=0",
                "for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -o '[0-9]\\+'); do",
                '  n=$((n + 1)); if [ "$pid" = "$sim" ]; then ours=1; fi',
                "done",
                'echo "GPU_PROCESSES=$n SIM_SERVER=$ours"',
                "",
            ]
        )

    def sim_state_script(self) -> str:
        """Prints SIM_STATE=not_set_up, port_taken (a listener on the port that isn't this account's: ss shows no pid for
        another account's process), ready, or else what the team's server process is doing (_SIM_PROCESS): starting,
        stuck, exited, or not_running when there's no pid file."""
        c = self.config
        return "\n".join(
            [
                f"DIR={shlex.quote(c.gb10_sim_dir)}; PY={shlex.quote(c.gb10_isaac_python)}; PORT={c.gb10_sim_port}",
                'if [ ! -d "$DIR" ] || [ ! -x "$PY" ]; then echo SIM_STATE=not_set_up; exit 0; fi',
                'listener=$(ss -ltnpH "sport = :$PORT" 2>/dev/null | head -n 1)',
                "if [ -n \"$listener\" ] && ! printf '%s' \"$listener\" | grep -q 'pid='; then echo SIM_STATE=port_taken; exit 0; fi",
                'if curl -s -m 5 "http://127.0.0.1:$PORT/health" | grep -q \'"status":"ok"\'; then echo SIM_STATE=ready; exit 0; fi',
                _SIM_PROCESS,
                'cd "$DIR"; process=$(sim_process)',
                'if [ "$process" = none ]; then echo SIM_STATE=not_running; else echo "SIM_STATE=$process"; fi',
                "",
            ]
        )

    def start_sim_script(self) -> str:
        """Starts the sim server unless the team's is already starting or running; a stuck one is killed first. The lock
        makes two teammates' starts take turns; the second finds the first's process alive and leaves it. The server
        gets its own session (setsid), so it outlives the ssh call, and not the lock (9>&-), so the lock is free once
        it's started. Each start gets a fresh runs/sim_server.log (the last one is kept as sim_server.prev.log), so the
        stuck check reads only this start's output. Prints SIM_START=started, already_running or locked."""
        c = self.config
        extra = f" {c.gb10_sim_args.strip()}" if c.gb10_sim_args.strip() else ""
        return "\n".join(
            [
                f"DIR={shlex.quote(c.gb10_sim_dir)}; PY={shlex.quote(c.gb10_isaac_python)}; PORT={c.gb10_sim_port}",
                'cd "$DIR" || exit 1',
                "mkdir -p runs",
                "exec 9>runs/sim_server.lock",
                "flock -w 30 9 || { echo SIM_START=locked; exit 0; }",
                _SIM_PROCESS,
                "case $(sim_process) in",
                "  starting) echo SIM_START=already_running; exit 0 ;;",
                '  stuck) pid=$(cat runs/sim_server.pid); kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid"; sleep 1 ;;',
                "esac",
                "if [ -f runs/sim_server.log ]; then mv -f runs/sim_server.log runs/sim_server.prev.log; fi",
                f'setsid "$PY" -m sim_server --port "$PORT"{extra} > runs/sim_server.log 2>&1 < /dev/null 9>&- &',
                "echo $! > runs/sim_server.pid",
                "echo SIM_START=started",
                "",
            ]
        )

    def _script(self, script: str, what: str) -> str:
        """Run a script on the GB10 (on stdin to bash -s) and return its output."""
        command = [*self.ssh, *SSH_OPTIONS, self.target, "bash", "-s"]
        try:
            done = self._run(command, input=script.encode(), capture_output=True, timeout=SSH_TIMEOUT_S, **NO_WINDOW)
        except FileNotFoundError:
            raise ComputeError(f"can't run ssh ({self.ssh[0]}): install OpenSSH (SETUP.md) or set COMPUTE_SSH") from None
        except subprocess.TimeoutExpired:
            raise ComputeError(f"{what} didn't finish within {SSH_TIMEOUT_S} s") from None
        out, err = _text(done.stdout), _text(done.stderr)
        if done.returncode == 255:
            raise ComputeError(self._ssh_failure(err))
        if done.returncode != 0:
            raise ComputeError(f"{what} failed: {_last_line(err) or _last_line(out) or f'exit code {done.returncode}'}")
        return out

    def _ssh_failure(self, stderr: str) -> str:
        host = self.config.gb10_host
        kind = next((kind for pattern, kind in SSH_FAILURES if pattern.search(stderr)), None)
        if kind == "host_key":
            return f"the GB10's host key changed ({host}): ask the organizers before trusting it"
        if kind == "permission":
            return f"the GB10 refused the login as {self.config.gb10_user}: add your SSH key to it (SETUP.md)"
        if kind == "unreachable":
            return f"can't reach the GB10 ({host}): connect the MSOE VPN (GlobalProtect)"
        return f"ssh to the GB10 failed: {_last_line(stderr) or 'no message'}"


def brev_command(config: ComputeConfig) -> list[str]:
    """The argv prefix that runs the Brev CLI: COMPUTE_BREV_CLI as a shell would split it, or, with COMPUTE_BREV_WSL,
    that run from a login shell in the WSL distro with every following argument passed through untouched."""
    if not config.brev_wsl:
        return shlex.split(config.brev_cli)
    return ["wsl", "-d", config.brev_wsl, "-e", "bash", "-lc", f'exec {config.brev_cli} "$@"', "brev"]


def create_compute_client(backend: ComputeBackend, config: ComputeConfig, data_dir: Path) -> ComputeClient:
    """The client for one backend. A session's process builds it from the session's backend."""
    if backend == "brev":
        return BrevCompute(config)
    if backend == "gb10":
        return Gb10Compute(config)
    return MockCompute(data_dir / "mock_compute.json")


def create_compute_clients(config: ComputeConfig, data_dir: Path) -> dict[ComputeBackend, ComputeClient]:
    """One client per enabled backend (COMPUTE_BACKENDS), for the API."""
    clients = {backend: create_compute_client(backend, config, data_dir) for backend in config.enabled}
    logger.info("Compute clients: %s", ", ".join(clients))
    return clients


def _brev_instance(workspace: dict) -> ComputeInstance:
    status = str(workspace.get("status") or "UNKNOWN").upper()
    gpu = workspace.get("gpu")
    return ComputeInstance(
        backend="brev",
        name=str(workspace["name"]),
        id=str(workspace.get("id") or workspace["name"]),
        status=status,
        state=BREV_STATES.get(status, "other"),
        gpu=None if gpu in (None, "", "-") else str(gpu),
        instance_type=workspace.get("instance_type"),
    )


def _text(value: bytes | str | None) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def _last_line(text: str | None) -> str:
    lines = [line.strip() for line in ANSI.sub("", text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""
