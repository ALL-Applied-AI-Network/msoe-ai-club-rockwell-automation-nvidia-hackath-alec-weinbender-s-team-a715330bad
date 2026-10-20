"""The compute backends: the mock's shared state, and the Brev CLI and ssh to the GB10, each driven through a fake
runner. (The GB10 scripts were also run by hand in WSL against a stand-in server: not running, started, already running,
ready, one server.)"""

import base64
import json
import re
import subprocess

import pytest
from pydantic import SecretStr

from api.clients.compute import (
    BrevCompute,
    ComputeError,
    Gb10Compute,
    MockCompute,
    create_compute_client,
    create_compute_clients,
)
from api.config import ComputeConfig

# ------------------------------------------------------------------ mock


def test_mock_instances_start_stopped_and_share_their_state_through_the_file(tmp_path):
    path = tmp_path / "mock_compute.json"
    api_side, session_side = MockCompute(path), MockCompute(path)

    assert {i.name: i.state for i in api_side.instances()} == {"mock-rtx-pro-4500": "stopped", "mock-l40s": "stopped"}
    assert all(i.backend == "mock" and not i.always_on for i in api_side.instances())
    session_side.start("mock-l40s")

    instance = next(i for i in api_side.instances() if i.name == "mock-l40s")
    assert (instance.state, instance.status, instance.gpu) == ("running", "RUNNING", "L40S")
    assert api_side.sim_state("mock-l40s") == "ready"
    session_side.stop("mock-l40s")
    assert api_side.sim_state("mock-l40s") == "host_not_ready"
    assert api_side.forward_command("mock-l40s", 9000) is None


def test_the_mock_refuses_an_instance_it_doesnt_have(tmp_path):
    with pytest.raises(ComputeError, match="no instance"):
        MockCompute(tmp_path / "state.json").start("rtx-9090")


# ------------------------------------------------------------------ Brev, through a fake CLI runner


class FakeCli:
    """Records each command and answers with the next queued (returncode, stdout, stderr), or ok and empty."""

    def __init__(self, *answers: tuple[int, str, str] | Exception):
        self.answers = list(answers)
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.kwargs.append(kwargs)
        answer = self.answers.pop(0) if self.answers else (0, "", "")
        if isinstance(answer, Exception):
            raise answer
        code, out, err = answer
        return subprocess.CompletedProcess(command, code, out, err)


def brev(*answers, **config) -> tuple[BrevCompute, FakeCli]:
    cli = FakeCli(*answers)
    return BrevCompute(ComputeConfig(backends="brev", **config), run=cli), cli


def sent_script(command: list[str]) -> str:
    """The script a `brev exec` command carries (base64 in "echo ... | base64 -d | bash")."""
    assert command[-3] == "exec"
    encoded = re.fullmatch(r"echo (\S+) \| base64 -d \| bash", command[-1])[1]
    return base64.b64decode(encoded).decode()


LS_JSON = json.dumps(
    {
        "workspaces": [
            {"name": "isaac-launchable-1e8a9b", "id": "aiimirjl2", "status": "STOPPED", "instance_type": "g7.2xlarge", "gpu": "-"},
            {"name": "trainer", "id": "x1", "status": "RUNNING", "instance_type": "g6e.xlarge", "gpu": "L40S"},
            {"name": "odd", "id": "x2", "status": "FAILURE"},
        ]
    }
)


def test_instances_come_from_ls_json_even_after_a_notice():
    client, cli = brev((0, "A new version of brev is available\n" + LS_JSON, ""))

    instances = client.instances()

    assert cli.commands == [["brev", "ls", "--json"]]
    assert [(i.name, i.status, i.state, i.gpu, i.instance_type) for i in instances] == [
        ("isaac-launchable-1e8a9b", "STOPPED", "stopped", None, "g7.2xlarge"),
        ("trainer", "RUNNING", "running", "L40S", "g6e.xlarge"),
        ("odd", "FAILURE", "other", None, None),
    ]


@pytest.mark.parametrize("out", ["not json at all", '{"something": "else"}', '{"workspaces": [{"id": "no-name"}]}'])
def test_an_unreadable_instance_list_is_a_compute_error(out):
    client, _ = brev((0, out, ""))

    with pytest.raises(ComputeError, match="instance list"):
        client.instances()


def test_the_cli_setting_is_split_like_a_shell():
    client, cli = brev(brev_cli="/opt/brev/brev --no-check-latest")

    client.start("isaac-launchable-1e8a9b")
    client.stop("isaac-launchable-1e8a9b")

    assert cli.commands == [
        ["/opt/brev/brev", "--no-check-latest", "start", "isaac-launchable-1e8a9b", "--detached"],
        ["/opt/brev/brev", "--no-check-latest", "stop", "isaac-launchable-1e8a9b"],
    ]
    assert all(kwargs["stdin"] is subprocess.DEVNULL and kwargs["timeout"] > 0 for kwargs in cli.kwargs)


def test_on_windows_the_cli_runs_in_a_wsl_login_shell_that_passes_arguments_untouched():
    """Not `wsl -- brev ...`: that runs the line through a shell that drops the quoting, so a `brev exec` script's pipe
    would run on the laptop. Checked on Windows 11 with WSL 2 (2026-10-20): "$@" arrives exactly as sent."""
    client, cli = brev(brev_wsl="Ubuntu")

    client.start_sim("box")

    prefix = ["wsl", "-d", "Ubuntu", "-e", "bash", "-lc", 'exec brev "$@"', "brev"]
    assert cli.commands[0][: len(prefix)] == prefix
    assert cli.commands[0][len(prefix) : len(prefix) + 2] == ["exec", "box"]
    assert sent_script(cli.commands[0]).startswith("docker exec -d vscode")


def test_the_sim_state_check_looks_at_the_container_then_the_health_endpoint():
    client, cli = brev((0, "some banner\nSIM_STATE=host_not_ready\n", ""), sim_port=9100)

    assert client.sim_state("box") == "host_not_ready"

    script = sent_script(cli.commands[0])
    assert "docker ps --filter name=^vscode$" in script
    assert "curl -s -m 5 http://127.0.0.1:9100/health" in script


def test_without_a_container_only_the_health_endpoint_is_checked():
    client, cli = brev((0, "SIM_STATE=ready", ""), sim_container="")

    assert client.sim_state("box") == "ready"
    assert "docker" not in sent_script(cli.commands[0])


def test_a_sim_state_it_cant_read_is_a_compute_error():
    client, _ = brev((0, "bash: curl: command not found", ""))

    with pytest.raises(ComputeError, match="curl: command not found"):
        client.sim_state("box")


def test_starting_the_sim_runs_the_server_detached_in_the_isaac_container():
    client, cli = brev(sim_args="--envs 64")

    client.start_sim("box")

    script = sent_script(cli.commands[0])
    assert script.startswith("docker exec -d vscode bash -lc ")
    assert (
        "cd /root/repo && mkdir -p runs && exec /isaac-sim/python.sh -m sim_server --port 9000 --envs 64 >> runs/sim_server.log" in script
    )


def test_without_a_container_the_sim_starts_with_nohup_on_the_machine():
    client, cli = brev(sim_container="", sim_dir="/home/ubuntu/repo", isaac_python="/opt/isaac/python.sh")

    client.start_sim("box")

    script = sent_script(cli.commands[0])
    assert script.startswith("nohup bash -lc ") and script.rstrip().endswith("&")
    assert "/opt/isaac/python.sh -m sim_server --port 9000 >> runs/sim_server.log" in script


def test_the_forward_maps_the_local_port_to_the_sim_port():
    client, _ = brev(sim_port=9100)

    assert client.forward_command("box", 9000) == ["brev", "port-forward", "box", "-p", "9000:9100"]


def test_a_token_logs_in_once_and_never_shows_up_in_errors():
    client, cli = brev((0, "", ""), (0, LS_JSON, ""), (1, "", "Error: workspace not found: box"), brev_token=SecretStr("brev-secret"))

    client.instances()
    with pytest.raises(ComputeError) as failed:
        client.stop("box")

    assert cli.commands[0] == ["brev", "login", "--token", "brev-secret"]
    assert [c[1] for c in cli.commands[1:]] == ["ls", "stop"]
    assert str(failed.value) == "brev stop failed: Error: workspace not found: box"
    assert "brev-secret" not in str(failed.value)


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (FileNotFoundError(), "can't run the Brev CLI (brev): install it (SETUP.md), or set COMPUTE_BREV_CLI or COMPUTE_BREV_WSL"),
        (subprocess.TimeoutExpired(["brev"], 120), "brev ls didn't finish within 120 s"),
        ((2, "", "\x1b[31mError: not logged in\x1b[0m\n"), "brev ls failed: Error: not logged in"),
        ((3, "", ""), "brev ls failed: exit code 3"),
    ],
)
def test_cli_failures_become_compute_errors_that_say_what_happened(answer, message):
    client, _ = brev(answer)

    with pytest.raises(ComputeError) as failed:
        client.instances()

    assert str(failed.value) == message


# ------------------------------------------------------------------ the GB10, over ssh through a fake runner


def gb10(*answers, **config) -> tuple[Gb10Compute, FakeCli]:
    cli = FakeCli(*answers)
    return Gb10Compute(ComputeConfig(backends="gb10", **config), run=cli), cli


SSH_PREFIX = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]


@pytest.mark.parametrize(
    ("out", "status", "others"),
    [
        (b"GPU_PROCESSES=0 SIM_SERVER=0\n", "AVAILABLE", 0),
        (b"GPU_PROCESSES=1 SIM_SERVER=1\n", "AVAILABLE", 0),  # only our sim server
        (b"GPU_PROCESSES=1 SIM_SERVER=0\n", "BUSY", 1),
        (b"GPU_PROCESSES=3 SIM_SERVER=1", "BUSY", 2),
    ],
    ids=["idle", "only ours", "another", "ours and two others"],
)
def test_the_gb10_is_one_always_on_target_with_the_gpu_processes_besides_our_sim_server(out, status, others):
    client, cli = gb10((0, out, b""))

    [target] = client.instances()

    assert (target.backend, target.name, target.id, target.state, target.always_on) == (
        "gb10",
        "spark1",
        "spark1.ai.msoe.edu",
        "running",
        True,
    )
    assert (target.status, target.other_gpu_processes, target.gpu) == (status, others, "NVIDIA GB10")
    script = cli.kwargs[0]["input"].decode()
    assert "nvidia-smi --query-compute-apps" in script and 'PORT=9011\nsim=$(ss -ltnpH "sport = :$PORT"' in script


def test_every_gb10_call_is_batch_ssh_with_its_script_on_stdin_as_lf_bytes():
    client, cli = gb10(
        (0, b"GPU_PROCESSES=0 SIM_SERVER=0", b""),
        (0, b"SIM_STATE=ready", b""),
        (0, b"SIM_START=started", b""),
        ssh="C:/Windows/System32/OpenSSH/ssh.exe",
    )

    client.instances()
    client.sim_state("spark1")
    client.start_sim("spark1")

    for command, kwargs in zip(cli.commands, cli.kwargs, strict=True):
        assert command == ["C:/Windows/System32/OpenSSH/ssh.exe", *SSH_PREFIX[1:], "hackathon11@spark1.ai.msoe.edu", "bash", "-s"]
        assert isinstance(kwargs["input"], bytes) and b"\r" not in kwargs["input"]


def test_the_gb10_scripts_quote_their_paths():
    client, cli = gb10(
        (0, b"SIM_STATE=not_running", b""),
        (0, b"SIM_START=started", b""),
        gb10_sim_dir="/home/hackathon11/my repo",
        gb10_isaac_python="/home/hackathon11/isaac sim/python.sh",
        gb10_sim_args="--envs 16",
    )

    client.sim_state("spark1")
    client.start_sim("spark1")

    state, start = (kwargs["input"].decode() for kwargs in cli.kwargs)
    assert "DIR='/home/hackathon11/my repo'; PY='/home/hackathon11/isaac sim/python.sh'; PORT=9011" in state
    assert 'ss -ltnpH "sport = :$PORT"' in state and 'curl -s -m 5 "http://127.0.0.1:$PORT/health"' in state
    assert "flock -w 30 9" in start and "kill -0" in start
    assert 'setsid "$PY" -m sim_server --port "$PORT" --envs 16 > runs/sim_server.log 2>&1 < /dev/null 9>&- &' in start


def test_the_gb10_scripts_call_a_start_stuck_when_kit_never_started_and_the_start_script_kills_it():
    client = Gb10Compute(ComputeConfig(backends="gb10"))
    state, start = client.sim_state_script(), client.start_sim_script()

    for script in (state, start):
        assert 'readlink "/proc/$pid/fd/1"' in script and 'ge 90 ] && ! grep -q "Simulation App Startup Complete" "$log"' in script
    assert 'echo "SIM_STATE=$process"' in state
    assert 'stuck) pid=$(cat runs/sim_server.pid); kill -KILL -- "-$pid"' in start
    assert "mv -f runs/sim_server.log runs/sim_server.prev.log" in start  # each start's own log, for the stuck check


@pytest.mark.parametrize(
    ("out", "message"),
    [
        (b"SIM_STATE=not_set_up", "GB10 not set up"),
        (b"SIM_STATE=port_taken", "port 9011 on the GB10 is held by another account: set COMPUTE_GB10_SIM_PORT"),
        (b"bash: ss: command not found", "couldn't read the sim server's state on the GB10"),
    ],
)
def test_a_gb10_that_cant_serve_says_why(out, message):
    client, _ = gb10((0, out, b""))

    with pytest.raises(ComputeError, match=re.escape(message)):
        client.sim_state("spark1")


@pytest.mark.parametrize(
    ("out", "state"),
    [
        (b"SIM_STATE=ready", "ready"),
        (b"motd line\nSIM_STATE=not_running\n", "not_running"),
        (b"SIM_STATE=starting", "starting"),
        (b"SIM_STATE=exited", "exited"),
        (b"SIM_STATE=stuck", "stuck"),
    ],
)
def test_the_gb10_sim_state_reads_the_script(out, state):
    client, _ = gb10((0, out, b""))

    assert client.sim_state("spark1") == state


@pytest.mark.parametrize(
    ("out", "fails"), [(b"SIM_START=started", False), (b"SIM_START=already_running", False), (b"SIM_START=locked", True)]
)
def test_starting_the_gb10_sim_leaves_a_running_server_alone(out, fails):
    client, _ = gb10((0, out, b""))

    if fails:
        with pytest.raises(ComputeError, match="a teammate is starting"):
            client.start_sim("spark1")
    else:
        client.start_sim("spark1")


def test_the_gb10_is_never_started_or_stopped():
    client, cli = gb10()

    client.start("spark1")
    client.stop("spark1")

    assert cli.commands == []


def test_the_gb10_forward_maps_the_local_port_to_its_sim_port():
    client, _ = gb10(gb10_sim_port=9012)

    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]
    assert client.forward_command("spark1", 9000) == [
        "ssh",
        "-N",
        *options,
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=30",
        "-L",
        "127.0.0.1:9000:127.0.0.1:9012",
        "hackathon11@spark1.ai.msoe.edu",
    ]


@pytest.mark.parametrize(
    ("stderr", "message"),
    [
        (b"ssh: Could not resolve hostname spark1.ai.msoe.edu: No such host is known.", "connect the MSOE VPN"),
        (b"ssh: connect to host spark1.ai.msoe.edu port 22: Connection timed out", "connect the MSOE VPN"),
        (b"hackathon11@spark1.ai.msoe.edu: Permission denied (publickey,password).", "add your SSH key to it (SETUP.md)"),
        (b"Host key verification failed.", "host key changed (spark1.ai.msoe.edu): ask the organizers"),
        (b"kex_exchange_identification: read: Connection reset", "ssh to the GB10 failed: kex_exchange_identification"),
    ],
)
def test_ssh_failures_say_what_to_do(stderr, message):
    client, _ = gb10((255, b"", stderr))

    with pytest.raises(ComputeError, match=re.escape(message)):
        client.instances()


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (FileNotFoundError(), "can't run ssh (ssh): install OpenSSH (SETUP.md) or set COMPUTE_SSH"),
        (subprocess.TimeoutExpired(["ssh"], 60), "checking the GB10 didn't finish within 60 s"),
        (
            (1, b"", b"bash: line 1: nvidia-smi: Input/output error\n"),
            "checking the GB10 failed: bash: line 1: nvidia-smi: Input/output error",
        ),
    ],
)
def test_other_gb10_failures_become_compute_errors(answer, message):
    client, _ = gb10(answer)

    with pytest.raises(ComputeError) as failed:
        client.instances()

    assert str(failed.value) == message


# ------------------------------------------------------------------ the factories


@pytest.mark.parametrize(
    ("backend", "kind", "always_on"), [("mock", MockCompute, False), ("brev", BrevCompute, False), ("gb10", Gb10Compute, True)]
)
def test_the_factory_builds_each_backend(backend, kind, always_on, tmp_path):
    client = create_compute_client(backend, ComputeConfig(), tmp_path)

    assert isinstance(client, kind) and (client.backend, client.always_on) == (backend, always_on)


def test_the_api_gets_one_client_per_enabled_target(tmp_path):
    clients = create_compute_clients(ComputeConfig(backends="gb10,brev"), tmp_path)

    assert list(clients) == ["gb10", "brev"]
