"""GPU sessions: connect one target's sim server to the app's SIM_URL, keep it connected while jobs use it, and end it
when the user asks. One target at a time, since every target forwards to the same local port.

- Brev: a session starts the instance (they're created in the Brev console; the app only starts, watches and stops
  them) and stops it when asked, after COMPUTE_AUTO_STOP_MINUTES with no job or prediction running, or when it fails.
- The MSOE GB10 is always on and shared with other teams (the client's always_on): a session starts the sim server
  there only if it isn't running, and disconnecting closes only the port forward, leaving the server running for
  teammates. Nothing stops by itself: one person's idle timer must not end a teammate's job on the shared server.

The API side (start_session, stop_session, claim, recover) only writes the session row and launches the session process
(python -m api.compute_worker <id>), which does the slow part in run_session: start the instance, start the sim server on
it, forward its port to SIM_URL's port here, then watch until it's time to stop. That process is detached like the job
workers, so auto-stop keeps working while the API restarts, and it owns the port forward the workers' sim requests go
through. It builds its client from the session's backend.

With a real target enabled (brev, gb10), a job, a resume or a test-plan prediction needs a ready session (claim). With
only the mock, nothing waits for it.
"""

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select

from api.clients.compute import ComputeClient, ComputeError
from api.clients.database import DatabaseClient
from api.clients.sim import SimClient
from api.config import AppConfig
from api.db.tables import ClipRow, ComputeSessionRow, JobRow, TestPlanRow
from api.models.clip import ACTIVE_CLIP_STATUSES
from api.models.compute import ACTIVE_SESSION_STATUSES, BACKEND_LABELS, ComputeInstance, ComputeSession, StopReason
from api.models.job import ACTIVE_STATUSES
from api.services.processes import pid_alive, spawn_detached, stop_tree

logger = logging.getLogger(__name__)

MANAGED_BACKENDS = ("brev", "gb10")
WATCH_POLL_S = 30  # how often a ready session checks for work, its instance and the sim
NAP_STEP_S = 5  # a stop request is seen within this, between watch polls
INSTANCE_CHECK_EVERY = 2  # watch polls between instance checks (the provider call is the slow one)
STEP_POLL_S = 10  # while starting or stopping
FORWARD_TIMEOUT_S = 120  # for the sim to answer through a new port forward
SIM_RESTART_TIMEOUT_S = 600  # for a sim server started again while connected to come back
SIM_START_ATTEMPTS = 3  # Isaac Sim fails about 1 start in 4 on the GB10, and every retry worked (2026-10-20)
STOP_TIMEOUT_S = 600
PREDICTION_STALE_S = 6 * 3600  # an unfinished prediction older than this has lost its worker: it doesn't keep a GPU up


class ComputeNotReadyError(RuntimeError):
    """The app manages the GPU and no ready session can take sim work. The message says what to do."""


class ComputeBusyError(RuntimeError):
    """Another target's session is still active: one at a time, since they share SIM_URL's port."""


class InstanceNotFoundError(LookupError):
    pass


class NoSessionError(LookupError):
    pass


class _StopRequested(Exception):
    pass


def managed(config: AppConfig) -> bool:
    """Is a real target enabled (and so must jobs wait for a ready session)?"""
    return any(backend in MANAGED_BACKENDS for backend in config.compute.enabled)


def get_session(db: DatabaseClient, session_id: int) -> ComputeSession:
    with db.session() as s:
        row = s.get(ComputeSessionRow, session_id)
        if row is None:
            raise NoSessionError(f"no GPU session {session_id}")
        return ComputeSession.model_validate(row)


def current_session(db: DatabaseClient) -> ComputeSession | None:
    """The session that's starting, ready or stopping, if any."""
    with db.session() as s:
        row = s.scalars(
            select(ComputeSessionRow).where(ComputeSessionRow.status.in_(ACTIVE_SESSION_STATUSES)).order_by(ComputeSessionRow.id.desc())
        ).first()
        return None if row is None else ComputeSession.model_validate(row)


def list_sessions(db: DatabaseClient, limit: int = 20) -> list[ComputeSession]:
    """The latest sessions first, ended ones included: a log of GPU time."""
    with db.session() as s:
        rows = s.scalars(select(ComputeSessionRow).order_by(ComputeSessionRow.id.desc()).limit(limit))
        return [ComputeSession.model_validate(row) for row in rows]


def start_session(db: DatabaseClient, config: AppConfig, client: ComputeClient, instance: str) -> ComputeSession:
    """Start connecting a target for the sim and return its session (status "starting"). Asking again for the target
    that's already up or starting returns that session."""
    current = current_session(db)
    if current is not None:
        if (current.backend, current.instance) == (client.backend, instance) and current.status != "stopping":
            return current
        raise ComputeBusyError(_busy_message(current))
    if instance not in {i.name for i in client.instances()}:
        where = "create it in the Brev console, then refresh" if client.backend == "brev" else "refresh the list"
        raise InstanceNotFoundError(f"{BACKEND_LABELS[client.backend]} has no target {instance!r}: {where}")
    with db.session() as s:
        row = ComputeSessionRow(backend=client.backend, instance=instance, status="starting", message="Starting")
        s.add(row)
        s.flush()
        session_id = row.id
    logger.info("GPU session %d: starting %s on %s", session_id, instance, client.backend)
    spawn_session(db, config, session_id)
    return get_session(db, session_id)


def _busy_message(current: ComputeSession) -> str:
    if current.status == "stopping":
        return f"{current.instance} is still stopping: wait until it has, then start another target"
    if current.backend == "gb10":
        return "The GB10 is connected: disconnect it before starting another target"
    return f"{current.instance} on {BACKEND_LABELS[current.backend]} is {current.status}: stop it before starting another target"


def stop_session(db: DatabaseClient, config: AppConfig) -> ComputeSession:
    """Ask the current session to end: stop its Brev instance, or disconnect from the GB10. Its process sees it within
    a few seconds; if that process is gone, a new one is started to do it."""
    current = current_session(db)
    if current is None:
        raise NoSessionError("no GPU session is running")
    ending = "Disconnecting" if current.backend == "gb10" else "Stopping"
    _update(db, current.id, stop_requested=1, message=ending if current.status != "stopping" else current.message)
    if not pid_alive(current.pid):
        spawn_session(db, config, current.id)
    return get_session(db, current.id)


def spawn_session(db: DatabaseClient, config: AppConfig, session_id: int) -> None:
    """Start the detached session process, python -m api.compute_worker <session_id>."""
    pid = spawn_detached([sys.executable, "-m", "api.compute_worker", str(session_id)], config.compute_log)
    _update(db, session_id, pid=pid)
    logger.info("GPU session %d: process started (pid %s)", session_id, pid)


def recover(db: DatabaseClient, config: AppConfig) -> None:
    """At API startup: an active session whose process is gone (the laptop restarted) has nobody to stop its instance
    or hold its forward, so start a new process, which carries on from the session's status."""
    current = current_session(db)
    if current is not None and not pid_alive(current.pid):
        logger.warning("GPU session %d (%s, %s): its process is gone; restarting it", current.id, current.instance, current.status)
        spawn_session(db, config, current.id)


def not_ready_reason(db: DatabaseClient, config: AppConfig) -> str | None:
    """Why sim work can't start now, or None when it can (always, unless a real target is enabled)."""
    if not managed(config):
        return None
    current = current_session(db)
    if current is None:
        return "The GPU isn't connected: choose a target in the GPU panel and start or connect it."
    if current.status == "starting":
        return f"The GPU ({current.instance}) is still starting: wait until it's ready."
    if current.status == "stopping":
        return f"The GPU ({current.instance}) is stopping: start it again once it has stopped."
    return None


def claim(db: DatabaseClient, config: AppConfig) -> None:
    """Before starting sim work (a job, a resume, a prediction): raise ComputeNotReadyError unless it can run, and mark
    the session in use, which restarts its idle clock."""
    reason = not_ready_reason(db, config)
    if reason is not None:
        raise ComputeNotReadyError(reason)
    current = current_session(db)
    if current is not None:
        _update(db, current.id, last_active=time.time())


def active_work(db: DatabaseClient, now: float) -> bool:
    """Is a job or clip worker alive, or a test-plan prediction waiting or running? A prediction stores no worker pid, so
    one older than PREDICTION_STALE_S is taken as lost, or a dead worker would keep the GPU up for good."""
    with db.session() as s:
        pids = s.scalars(select(JobRow.pid).where(JobRow.status.in_(ACTIVE_STATUSES))).all()
        pids += s.scalars(select(ClipRow.pid).where(ClipRow.status.in_(ACTIVE_CLIP_STATUSES))).all()
        if any(pid_alive(pid) for pid in pids):
            return True
        predictions = s.scalar(
            select(func.count())
            .select_from(TestPlanRow)
            .where(TestPlanRow.prediction_status.in_(("pending", "running")), TestPlanRow.created > now - PREDICTION_STALE_S)
        )
        return bool(predictions)


def run_session(
    db: DatabaseClient,
    config: AppConfig,
    client: ComputeClient,
    sim: SimClient,
    session_id: int,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> None:
    """The session process's work (api/compute_worker.py): bring the target up, watch it, end it. Returns when the
    session has stopped or failed. A failed Brev session stops its instance too, so it can't use credits unattended."""
    session = get_session(db, session_id)
    if session.status not in ACTIVE_SESSION_STATUSES:
        logger.info("GPU session %d is already %s", session_id, session.status)
        return
    _Session(db, config, client, sim, session, sleep, clock).run()


class _Session:
    def __init__(self, db, config, client, sim, session: ComputeSession, sleep, clock):
        self.db, self.config, self.client, self.sim = db, config, client, sim
        self.id, self.name = session.id, session.instance
        self.sleep, self.clock = sleep, clock
        self.always_on = client.always_on  # the GB10: no instance to start or stop, no auto-stop
        self.auto_stop_s = 0.0 if self.always_on else config.compute.auto_stop_minutes * 60
        self.forward: subprocess.Popen | None = None

    def run(self) -> None:
        try:
            status = self._row().status
            if status == "starting":
                self._bring_up()
            elif status == "ready":  # a restarted session process: the old one's port forward ended with it
                self._connect()
            reason: StopReason = self._watch() if self._row().status == "ready" else "user"
        except _StopRequested:
            reason = "user"
        except (ComputeError, TimeoutError) as e:
            self._fail(str(e))
            return
        except Exception as e:  # anything else still has to end the session (and stop a Brev instance)
            logger.exception("GPU session %d failed", self.id)
            self._fail(f"{type(e).__name__}: {e}")
            return
        self._shut_down(reason)

    # ---- starting

    def _bring_up(self) -> None:
        deadline = self.clock() + self.config.compute.start_timeout_s
        asked = False
        while (instance := self._instance()).state != "running":
            self._check_stop()
            if instance.state in ("stopped", "other") and not asked:  # Brev lets a FAILURE instance be started again
                self._note(f"Starting {self.name} (a few minutes)")
                self.client.start(self.name)
                asked = True
            elif instance.state == "other":
                raise ComputeError(
                    f"{self.name} is {instance.status} on {BACKEND_LABELS[self.client.backend]} after the start request. That usually "
                    "means no GPU of its type is free in its region right now: try again in a few minutes, and see the "
                    "instance's Activity Logs in the Brev console for the reason."
                )
            self._wait(deadline, "the instance to start")
        self._start_sim(deadline)
        self._connect(deadline)
        now = self.clock()
        self._set(status="ready", ready_at=now, last_active=now, message=self._ready_message(0.0))
        logger.info("GPU session %d: %s ready", self.id, self.name)

    def _start_sim(self, deadline: float) -> None:
        """Wait until the sim server answers on the target, starting it if it isn't running. A start that exits or gets
        stuck (Isaac Sim on the GB10, about 1 time in 4) is tried again, up to SIM_START_ATTEMPTS starts in all. A
        target that can't tell a starting server from a stopped one (Brev) gets one start."""
        attempts = 0
        while (state := self.client.sim_state(self.name)) != "ready":
            self._check_stop()
            if state in ("exited", "stuck") or (state == "not_running" and attempts == 0):
                if attempts == SIM_START_ATTEMPTS:
                    raise ComputeError(
                        f"Isaac Sim didn't start on {self.name} in {attempts} tries: see runs/sim_server.log in the repo there"
                    )
                attempts += 1
                if attempts == 1:
                    self._note("Starting the sim server (Isaac Sim takes about a minute)")
                else:
                    how = "hung" if state == "stuck" else "exited"
                    self._note(f"Isaac Sim {how} while starting, as it sometimes does; trying again ({attempts} of {SIM_START_ATTEMPTS})")
                self.client.start_sim(self.name)
            elif state == "host_not_ready":
                self._note("Waiting for the instance's Isaac container")
            self._wait(deadline, "the sim server to start")

    def _connect(self, deadline: float | None = None) -> None:
        """(Re)open the port forward and wait for the sim to answer through it. A forward that already answers (one an
        earlier session process left behind, or one started by hand) is used as it is: a second can't take its port."""
        self._close_forward()
        if self.sim.health():
            return
        command = self.client.forward_command(self.name, self._local_port())
        log = self.config.data_dir / "compute_forward.log"
        if command is not None:
            self._note("Connecting to the sim server")
            log.parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a") as out:
                self.forward = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, **_CHILD)
        limit = self.clock() + FORWARD_TIMEOUT_S
        deadline = limit if deadline is None else min(deadline, limit)
        while not self.sim.health():
            if self.forward is not None and self.forward.poll() is not None:
                raise ComputeError(f"the port forward to {self.name} exited (code {self.forward.returncode}); see {log}")
            self._wait(deadline, "the sim server to answer through the port forward", step=2)

    # ---- watching

    def _watch(self) -> StopReason:
        polls = failures = 0
        while True:
            if self._nap(WATCH_POLL_S):
                return "user"
            row = self._row()
            now = self.clock()
            if active_work(self.db, now):
                self._set(last_active=now)
                row = self._row()
            idle = now - (row.last_active or row.ready_at or now)
            if self.auto_stop_s and idle >= self.auto_stop_s:
                return "idle"
            polls += 1
            if not self.always_on and polls % INSTANCE_CHECK_EVERY == 0:
                try:
                    if self._instance().state != "running":
                        return "external"
                except ComputeError as e:  # the provider didn't answer this time: keep going
                    logger.warning("GPU session %d: couldn't check %s: %s", self.id, self.name, e)
            if self.sim.health():
                failures = 0
                self._set(message=self._ready_message(idle))
                continue
            failures += 1
            if failures >= 2 or (self.forward is not None and self.forward.poll() is not None):  # one miss, or the forward ended
                self._recover_sim()
                if self.sim.health():
                    self._set(message=self._ready_message(idle))
                failures = 0

    def _recover_sim(self) -> None:
        """The sim stopped answering through the forward: start the server again if it has died on the target, then
        reconnect. A failure here (the VPN is down, say) is noted and retried at the next polls, never the end of the
        session: the jobs waiting for the sim (clients/sim.py) carry on once it answers again."""
        try:
            if self.client.sim_state(self.name) in ("not_running", "exited", "stuck"):
                self._note(f"The sim server on {self.name} stopped; starting it again")
                self._start_sim(self.clock() + SIM_RESTART_TIMEOUT_S)
            self._note("Reconnecting to the sim server")
            self._connect()
        except (ComputeError, TimeoutError) as e:
            wait = self.config.sim.reconnect_minutes
            jobs = f"running jobs wait up to {wait:g} min for it" if wait else "running jobs fail without it (SIM_RECONNECT_MINUTES=0)"
            self._note(f"The sim server isn't answering ({e}); retrying, and {jobs}")

    def _ready_message(self, idle_s: float) -> str:
        if self.always_on:
            return f"Connected; the sim server on {self.name} keeps running for teammates after you disconnect"
        if not self.auto_stop_s:
            return "Ready; auto-stop is off"
        return f"Ready; idle {idle_s / 60:.0f} min, stops after {self.auto_stop_s / 60:g} min without a job"

    # ---- ending

    def _shut_down(self, reason: StopReason) -> None:
        self._close_forward()
        if self.always_on:  # nothing to stop, and the server stays up for teammates
            self._set(status="stopped", stopped_at=self.clock(), stop_reason=reason, message="Disconnected; the sim server keeps running")
            logger.info("GPU session %d: disconnected from %s", self.id, self.name)
            return
        if reason == "external":
            self._set(status="stopped", stopped_at=self.clock(), stop_reason=reason, message="Stopped outside the app")
            logger.info("GPU session %d: %s was stopped outside the app", self.id, self.name)
            return
        why = f"idle for {self.auto_stop_s / 60:g} min" if reason == "idle" else "asked to"
        self._set(status="stopping", message=f"Stopping ({why})")
        try:
            self.client.stop(self.name)
            deadline = self.clock() + STOP_TIMEOUT_S
            while self._instance().state not in ("stopped", "other"):
                self._wait(deadline, "the instance to stop", interruptible=False)
        except (ComputeError, TimeoutError) as e:
            self._set(
                status="failed",
                stopped_at=self.clock(),
                stop_reason="failed",
                message=f"Couldn't stop {self.name} ({e}): stop it in the Brev console",
            )
            return
        self._set(status="stopped", stopped_at=self.clock(), stop_reason=reason, message=f"Stopped ({why})")
        logger.info("GPU session %d: %s stopped (%s)", self.id, self.name, why)

    def _fail(self, error: str) -> None:
        """A failed session closes its forward. On Brev it also stops the instance, so a half-started GPU can't run up
        credits unattended; the GB10 is left alone."""
        self._close_forward()
        message = error
        if not self.always_on:
            try:
                if self._instance().state in ("running", "starting"):
                    self.client.stop(self.name)
                    message += f"; stopped {self.name} so it doesn't use credits"
            except ComputeError as e:
                message += f"; couldn't stop {self.name} ({e}): stop it in the Brev console"
        self._set(status="failed", stopped_at=self.clock(), stop_reason="failed", message=message)
        logger.error("GPU session %d failed: %s", self.id, message)

    # ---- helpers

    def _instance(self) -> ComputeInstance:
        for instance in self.client.instances():
            if instance.name == self.name:
                return instance
        raise ComputeError(f"{self.name} is gone from {BACKEND_LABELS[self.client.backend]}")

    def _local_port(self) -> int:
        url = urlparse(self.config.sim.url or "")
        return url.port or (443 if url.scheme == "https" else 80)

    def _close_forward(self) -> None:
        if self.forward is not None:
            stop_tree(self.forward)
            self.forward = None

    def _check_stop(self) -> None:
        if self._row().stop_requested:
            raise _StopRequested

    def _wait(self, deadline: float, what: str, step: float = STEP_POLL_S, *, interruptible: bool = True) -> None:
        """Sleep a step before trying again, or raise TimeoutError past the deadline (and _StopRequested if asked)."""
        if self.clock() >= deadline:
            raise TimeoutError(f"gave up waiting for {what}")
        if interruptible:
            self._check_stop()
        self.sleep(step)

    def _nap(self, seconds: float) -> bool:
        """Sleep, in short steps so a stop request is seen within one. True if a stop was requested."""
        for _ in range(max(1, round(seconds / NAP_STEP_S))):
            if self._row().stop_requested:
                return True
            self.sleep(min(NAP_STEP_S, seconds))
        return bool(self._row().stop_requested)

    def _row(self) -> ComputeSession:
        return get_session(self.db, self.id)

    def _note(self, message: str) -> None:
        self._set(message=message)

    def _set(self, **values: Any) -> None:
        _update(self.db, self.id, **values)


# The port forward is the session process's child: its own process group (POSIX), so stop_tree() can end ssh with it,
# and no console window (the session process is detached, so on Windows one would open).
_CHILD: dict[str, Any] = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}


def _update(db: DatabaseClient, session_id: int, **values: Any) -> None:
    with db.session() as s:
        row = s.get(ComputeSessionRow, session_id)
        for name, value in values.items():
            setattr(row, name, value)
