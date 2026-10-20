"""GPU sessions: starting, stopping and the readiness check on the API side, and the session process's whole life
(run_session) against the mock backend, a fake always-on target (the GB10's behaviour) and a fake clock, so starting,
auto-stop and failures run in milliseconds."""

import sys
import time

import pytest

from api import compute_worker
from api.clients.compute import ComputeError, MockCompute
from api.clients.sim import MockSim
from api.config import AppConfig, ComputeConfig, SimConfig
from api.db.tables import ComputeSessionRow, JobRow, TestPlanRow
from api.models.compute import ComputeInstance
from api.services import compute, jobs
from api.services.compute import (
    ComputeBusyError,
    ComputeNotReadyError,
    InstanceNotFoundError,
    NoSessionError,
    claim,
    current_session,
    get_session,
    run_session,
    start_session,
    stop_session,
)

INSTANCE = "mock-rtx-pro-4500"


@pytest.fixture
def managed(tmp_path) -> AppConfig:
    """The app managing the GPU (brev), with the mock compute client standing in for the CLI in these tests."""
    return AppConfig(
        data_dir=tmp_path,
        sim=SimConfig(backend="http", url="http://127.0.0.1:9000"),
        compute=ComputeConfig(backends="brev", auto_stop_minutes=10, start_timeout_s=600),
    )


@pytest.fixture
def mock(config) -> MockCompute:
    return MockCompute(config.data_dir / "mock_compute.json")


class Clock:
    """time.time and time.sleep for the session process: sleeping moves the clock on, instantly."""

    def __init__(self):
        self.now = 1_000_000.0
        self.slept = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds


def a_session(db, status="ready", instance=INSTANCE, backend="mock", **values) -> int:
    with db.session() as s:
        row = ComputeSessionRow(backend=backend, instance=instance, status=status, **values)
        s.add(row)
        s.flush()
        return row.id


def state(mock: MockCompute, name: str = INSTANCE) -> str:
    return next(i.state for i in mock.instances() if i.name == name)


# ------------------------------------------------------------------ API side


def test_starting_records_a_session_and_launches_its_process(db, config, mock, spawned_sessions):
    session = start_session(db, config, mock, INSTANCE)

    assert (session.instance, session.status, session.backend, session.message) == (INSTANCE, "starting", "mock", "Starting")
    assert spawned_sessions == [session.id]
    assert current_session(db) == session


def test_asking_again_for_the_same_instance_returns_its_session(db, config, mock, spawned_sessions):
    first = start_session(db, config, mock, INSTANCE)

    assert start_session(db, config, mock, INSTANCE).id == first.id
    assert spawned_sessions == [first.id]


def test_one_instance_at_a_time(db, config, mock, spawned_sessions):
    start_session(db, config, mock, INSTANCE)

    with pytest.raises(ComputeBusyError, match="stop it before starting another"):
        start_session(db, config, mock, "mock-l40s")


def test_an_unknown_instance_points_at_the_console(db, config, mock, spawned_sessions):
    with pytest.raises(InstanceNotFoundError, match="Mock has no target 'rtx-9090': refresh the list"):
        start_session(db, config, mock, "rtx-9090")
    assert spawned_sessions == []


def test_stopping_asks_the_session_and_relaunches_a_process_that_is_gone(db, config, spawned_sessions):
    session_id = a_session(db, pid=None)

    stopped = stop_session(db, config)

    assert (stopped.id, stopped.stop_requested, stopped.message) == (session_id, 1, "Stopping")
    assert spawned_sessions == [session_id]


def test_stopping_with_nothing_running_says_so(db, config, spawned_sessions):
    a_session(db, status="stopped")

    with pytest.raises(NoSessionError):
        stop_session(db, config)


def test_recover_restarts_the_process_of_an_active_session(db, config, spawned_sessions):
    a_session(db, status="stopped")
    session_id = a_session(db, status="ready", pid=None)

    compute.recover(db, config)

    assert spawned_sessions == [session_id]


def test_with_the_mock_sim_work_never_waits_for_a_gpu(db, config):
    assert compute.not_ready_reason(db, config) is None
    claim(db, config)  # no session, no error


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (None, "isn't connected"),
        ("starting", "still starting"),
        ("stopping", "is stopping"),
        ("ready", None),
        ("stopped", "isn't connected"),
    ],
)
def test_a_managed_gpu_must_be_ready_for_sim_work(db, managed, status, reason):
    if status is not None:
        a_session(db, status=status)

    found = compute.not_ready_reason(db, managed)

    assert found is None if reason is None else reason in found


def test_claiming_a_ready_gpu_restarts_its_idle_clock(db, managed):
    session_id = a_session(db, last_active=1.0)

    claim(db, managed)

    assert get_session(db, session_id).last_active > time.time() - 60


def test_claiming_without_a_ready_gpu_raises(db, managed):
    with pytest.raises(ComputeNotReadyError, match="choose a target in the GPU panel"):
        claim(db, managed)


def test_a_job_isnt_created_until_the_gpu_is_ready(db, managed, spawned):
    with pytest.raises(ComputeNotReadyError):
        jobs.create_job(db, managed, spec=None)  # refused before the spec is looked at
    assert spawned == []


def test_active_work_is_a_live_job_worker_or_a_recent_prediction(db, monkeypatch):
    now = time.time()
    monkeypatch.setattr(compute, "pid_alive", lambda pid: pid == 42)
    assert not compute.active_work(db, now)

    with db.session() as s:
        s.add(JobRow(**_job_row(id="dead", pid=7, status="running", number=1)))
    assert not compute.active_work(db, now)
    with db.session() as s:
        s.add(JobRow(**_job_row(id="live", pid=42, status="running", number=2)))
    assert compute.active_work(db, now)


def test_an_old_unfinished_prediction_doesnt_keep_the_gpu_up(db):
    now = time.time()
    with db.session() as s:
        s.add(TestPlanRow(job_id="j", seed=1, designs=[], rows=[], prediction_status="running", created=now - 7 * 3600))
    assert not compute.active_work(db, now)
    with db.session() as s:
        s.add(TestPlanRow(job_id="j", seed=2, designs=[], rows=[], prediction_status="pending", created=now - 60))
    assert compute.active_work(db, now)


def _job_row(*, id: str, pid: int, status: str, number: int) -> dict:
    """A jobs row with just enough to store: active_work only reads status and pid."""
    from api.models.job import Job

    columns = JobRow.__table__.columns
    row = {name: None for name in Job.model_fields if name in columns and columns[name].nullable}
    row.update(
        id=id,
        experiment_number=number,
        name=id,
        status=status,
        part_id="p",
        cell_profile_id=1,
        sim_backend="mock",
        spec={"part_id": "p", "cell_profile_id": 1, "grasp": {"angle_deg": 0, "centre_mm": [0, 0], "source": "auto"}},
        part={"shape": "box", "box_mm": [10, 10, 10], "mass_g": 4},
        plan=None,
        pid=pid,
    )
    return row


# ------------------------------------------------------------------ the session process


def run(db, config, client, session_id, clock, sim=None):
    run_session(db, config, client, sim or MockSim(), session_id, sleep=clock.sleep, clock=clock.time)


def test_a_session_comes_up_then_stops_itself_after_the_idle_time(db, managed, mock):
    clock = Clock()
    session_id = a_session(db, status="starting")

    run(db, managed, mock, session_id, clock)

    session = get_session(db, session_id)
    assert (session.status, session.stop_reason) == ("stopped", "idle")
    assert session.ready_at - 1_000_000.0 <= compute.STEP_POLL_S  # the mock is running by the first check after start
    assert session.stopped_at - session.ready_at == pytest.approx(10 * 60, abs=60)
    assert session.message == "Stopped (idle for 10 min)"
    assert state(mock) == "stopped"


def test_work_keeps_the_session_up(db, managed, mock, monkeypatch):
    clock = Clock()
    session_id = a_session(db, status="starting")
    busy_until = clock.now + 30 * 60
    monkeypatch.setattr(compute, "active_work", lambda db, now: now < busy_until)

    run(db, managed, mock, session_id, clock)

    session = get_session(db, session_id)
    assert session.stop_reason == "idle"
    assert session.stopped_at >= busy_until + 10 * 60 - 60  # idle counted from the last work seen


def test_a_stop_request_ends_the_session_within_a_few_seconds(db, managed, mock, monkeypatch):
    clock = Clock()
    session_id = a_session(db, status="starting")
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        if clock.now >= 1_000_000.0 + 60:
            compute._update(db, session_id, stop_requested=1)

    clock.sleep = sleep
    run(db, managed, mock, session_id, clock)

    session = get_session(db, session_id)
    assert (session.status, session.stop_reason, session.message) == ("stopped", "user", "Stopped (asked to)")
    assert session.stopped_at - 1_000_000.0 <= 60 + compute.NAP_STEP_S
    assert state(mock) == "stopped"


def test_auto_stop_off_waits_for_the_user(db, managed, mock):
    managed.compute.auto_stop_minutes = 0
    clock = Clock()
    session_id = a_session(db, status="starting")
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        if clock.now >= 1_000_000.0 + 5 * 3600:
            compute._update(db, session_id, stop_requested=1)

    clock.sleep = sleep
    run(db, managed, mock, session_id, clock)

    assert get_session(db, session_id).stop_reason == "user"
    assert clock.now >= 1_000_000.0 + 5 * 3600


def test_an_instance_stopped_in_the_console_ends_the_session(db, managed, mock):
    clock = Clock()
    session_id = a_session(db, status="starting")
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        if clock.now >= 1_000_000.0 + 120:
            mock.stop(INSTANCE)  # someone used the Brev console

    clock.sleep = sleep
    run(db, managed, mock, session_id, clock)

    session = get_session(db, session_id)
    assert (session.status, session.stop_reason, session.message) == ("stopped", "external", "Stopped outside the app")


class SlowSim(MockCompute):
    """The instance boots, but the sim server never answers on it."""

    def sim_state(self, name):
        return "not_running"


def test_a_sim_that_never_starts_fails_the_session_and_stops_the_instance(db, managed, config):
    client = SlowSim(config.data_dir / "slow.json")
    clock = Clock()
    session_id = a_session(db, status="starting")

    run(db, managed, client, session_id, clock)

    session = get_session(db, session_id)
    assert (session.status, session.stop_reason) == ("failed", "failed")
    assert "gave up waiting for the sim server to start" in session.message
    assert f"stopped {INSTANCE} so it doesn't use credits" in session.message
    assert state(client) == "stopped"


class BrokenStart(MockCompute):
    def start_sim(self, name):
        raise ComputeError("brev exec failed: connection reset")

    def sim_state(self, name):
        return "not_running"


def test_a_provider_error_fails_the_session_with_its_message(db, managed, config):
    client = BrokenStart(config.data_dir / "broken.json")
    session_id = a_session(db, status="starting")

    run(db, managed, client, session_id, Clock())

    message = get_session(db, session_id).message
    assert message.startswith("brev exec failed: connection reset; stopped")


class Unhealthy(MockSim):
    def health(self):
        return False


def test_a_sim_that_doesnt_answer_through_the_forward_fails_the_session(db, managed, mock):
    session_id = a_session(db, status="starting")

    run(db, managed, mock, session_id, Clock(), sim=Unhealthy())

    session = get_session(db, session_id)
    assert session.status == "failed"
    assert "answer through the port forward" in session.message


def test_a_session_that_already_ended_is_left_alone(db, managed, mock):
    session_id = a_session(db, status="stopped", stop_reason="user")

    run(db, managed, mock, session_id, Clock())

    assert get_session(db, session_id).status == "stopped"


def test_a_restarted_process_picks_up_a_ready_session(db, managed, mock):
    mock.start(INSTANCE)
    session_id = a_session(db, status="ready", ready_at=1_000_000.0, last_active=1_000_000.0)

    run(db, managed, mock, session_id, Clock())

    assert get_session(db, session_id).stop_reason == "idle"


class Failed(MockCompute):
    """Brev after a start request that found no capacity: FAILURE before and after."""

    def __init__(self, path):
        super().__init__(path)
        self.starts = 0

    def instances(self):
        return [i.model_copy(update={"status": "FAILURE", "state": "other"}) for i in super().instances()]

    def start(self, name):
        self.starts += 1


def test_a_failed_brev_instance_is_tried_once_then_explained(db, managed, config):
    client = Failed(config.data_dir / "failed.json")
    session_id = a_session(db, status="starting")

    run(db, managed, client, session_id, Clock())

    session = get_session(db, session_id)
    assert client.starts == 1
    assert session.status == "failed" and "no GPU of its type is free" in session.message and "Activity Logs" in session.message


# ------------------------------------------------------------------ an always-on target (the GB10)


class AlwaysOn(MockCompute):
    """The GB10's behaviour: one target, always running, never started or stopped. The sim server can be made to die
    (crash()); start_sim brings it back."""

    backend = "gb10"
    always_on = True

    def __init__(self, path, *, sim_starts_ok=True):
        super().__init__(path)
        self.sim_up, self.sim_starts, self.stops = False, 0, 0
        self.sim_starts_ok = sim_starts_ok

    def instances(self):
        return [
            ComputeInstance(
                backend="gb10",
                name="spark1",
                id="spark1.ai.msoe.edu",
                status="AVAILABLE",
                state="running",
                gpu="NVIDIA GB10",
                always_on=True,
            )
        ]

    def stop(self, name):
        self.stops += 1

    def sim_state(self, name):
        return "ready" if self.sim_up else "not_running"

    def start_sim(self, name):
        self.sim_starts += 1
        self.sim_up = self.sim_starts_ok

    def crash(self):
        self.sim_up = False


class SimThrough(MockSim):
    """The sim as seen through the forward: answers only while the target's server is up."""

    def __init__(self, target: AlwaysOn):
        self.target = target

    def health(self):
        return self.target.sim_up


@pytest.fixture
def both(tmp_path) -> AppConfig:
    return AppConfig(
        data_dir=tmp_path,
        sim=SimConfig(backend="http", url="http://127.0.0.1:9000"),
        compute=ComputeConfig(backends="brev,gb10", auto_stop_minutes=10, start_timeout_s=600),
    )


def test_a_gb10_session_never_stops_by_itself_and_disconnecting_stops_nothing(db, both, config):
    target = AlwaysOn(config.data_dir / "gb10.json")
    clock = Clock()
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        if clock.now >= 1_000_000.0 + 3600:  # an idle hour: Brev would have stopped after ten minutes
            compute._update(db, session_id, stop_requested=1)

    clock.sleep = sleep
    run(db, both, target, session_id, clock, sim=SimThrough(target))

    session = get_session(db, session_id)
    assert (session.status, session.stop_reason, session.message) == ("stopped", "user", "Disconnected; the sim server keeps running")
    assert clock.now >= 1_000_000.0 + 3600
    assert (target.sim_starts, target.stops, target.sim_up) == (1, 0, True)  # started once, never stopped, left running


def test_a_gb10_server_already_running_is_used_as_it_is(db, both, config):
    target = AlwaysOn(config.data_dir / "gb10.json")
    target.sim_up = True  # a teammate's
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")
    compute._update(db, session_id, stop_requested=0)

    clock = Clock()
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        compute._update(db, session_id, stop_requested=1)

    clock.sleep = sleep
    run(db, both, target, session_id, clock, sim=SimThrough(target))

    assert target.sim_starts == 0 and get_session(db, session_id).status == "stopped"


def test_a_gb10_server_that_dies_is_started_again(db, both, config):
    target = AlwaysOn(config.data_dir / "gb10.json")
    clock = Clock()
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        if 1_000_000.0 + 600 <= clock.now < 1_000_000.0 + 605:
            target.crash()
        if clock.now >= 1_000_000.0 + 3600:
            compute._update(db, session_id, stop_requested=1)

    clock.sleep = sleep
    run(db, both, target, session_id, clock, sim=SimThrough(target))

    assert target.sim_starts == 2 and target.sim_up
    assert get_session(db, session_id).stop_reason == "user"


class BehindVpn(AlwaysOn):
    """The GB10 behind the MSOE VPN: while it's down, ssh can't reach the machine and the forward is cut, and it takes a
    new forward, opened once the VPN is back, to reach the sim again. Its forward is a process that has already ended,
    like ssh after the VPN drops."""

    def __init__(self, path):
        super().__init__(path)
        self.vpn_up, self.forwarded = True, False

    def drop_vpn(self):
        self.vpn_up = self.forwarded = False

    def sim_state(self, name):
        if not self.vpn_up:
            raise ComputeError("can't reach the GB10 (spark1.ai.msoe.edu): connect the MSOE VPN (GlobalProtect)")
        return super().sim_state(name)

    def forward_command(self, name, local_port):
        self.forwarded = self.vpn_up
        return [sys.executable, "-c", "pass"]


class SimThroughVpn(MockSim):
    def __init__(self, target: BehindVpn):
        self.target = target

    def health(self):
        return self.target.sim_up and self.target.forwarded


def test_a_vpn_outage_while_connected_is_waited_out_and_the_forward_reopened(db, both, config):
    target = BehindVpn(config.data_dir / "gb10.json")
    clock, start = Clock(), 1_000_000.0
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")
    notes: list[tuple[float, str]] = []
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        notes.append((clock.now - start, get_session(db, session_id).message))
        if start + 600 <= clock.now < start + 605:
            target.drop_vpn()  # twenty minutes without the VPN
        if start + 1800 <= clock.now < start + 1805:
            target.vpn_up = True
        if clock.now >= start + 3600:
            compute._update(db, session_id, stop_requested=1)

    clock.sleep = sleep
    run(db, both, target, session_id, clock, sim=SimThroughVpn(target))

    session = get_session(db, session_id)
    assert (session.status, session.stop_reason) == ("stopped", "user")  # the outage never ended the session
    during = [message for t, message in notes if 640 <= t < 1800]
    assert during and all("connect the MSOE VPN" in m and "running jobs wait up to 120 min" in m for m in during)
    back = next(t for t, message in notes if t >= 1800 and message.startswith("Connected"))
    assert back - 1800 <= compute.WATCH_POLL_S + compute.NAP_STEP_S  # the ended forward is replaced at the next poll
    assert target.forwarded and target.sim_starts == 1  # reconnected to the same server, not a new one


class FlakyIsaac(AlwaysOn):
    """The GB10's Isaac Sim start, which fails about 1 time in 4: each start_sim takes the next outcome, "ok", or the
    state a failed start leaves (exited: it segfaulted; stuck: it hung before Kit started)."""

    def __init__(self, path, outcomes):
        super().__init__(path)
        self.outcomes, self.after_start = list(outcomes), "not_running"

    def sim_state(self, name):
        return "ready" if self.sim_up else self.after_start

    def start_sim(self, name):
        self.sim_starts += 1
        outcome = self.outcomes.pop(0)
        self.sim_up, self.after_start = outcome == "ok", outcome


def test_an_isaac_start_that_exits_or_hangs_is_tried_again(db, both, config):
    target = FlakyIsaac(config.data_dir / "gb10.json", ["exited", "stuck", "ok"])
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")
    clock, notes = Clock(), []
    original = clock.sleep

    def sleep(seconds):
        original(seconds)
        notes.append(get_session(db, session_id).message)
        if get_session(db, session_id).status == "ready":
            compute._update(db, session_id, stop_requested=1)

    clock.sleep = sleep
    run(db, both, target, session_id, clock, sim=SimThrough(target))

    assert target.sim_starts == 3 and get_session(db, session_id).stop_reason == "user"  # it came up
    assert "Isaac Sim exited while starting, as it sometimes does; trying again (2 of 3)" in notes
    assert "Isaac Sim hung while starting, as it sometimes does; trying again (3 of 3)" in notes


def test_isaac_failing_every_start_fails_the_session_after_three_tries(db, both, config):
    target = FlakyIsaac(config.data_dir / "gb10.json", ["exited", "stuck", "exited"])
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")

    run(db, both, target, session_id, Clock(), sim=SimThrough(target))

    session = get_session(db, session_id)
    assert session.status == "failed" and "Isaac Sim didn't start on spark1 in 3 tries" in session.message
    assert target.sim_starts == 3 and target.stops == 0


def test_a_gb10_failure_stops_nothing_and_mentions_no_credits(db, both, config):
    target = AlwaysOn(config.data_dir / "gb10.json", sim_starts_ok=False)  # e.g. Isaac Sim won't start there
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")

    run(db, both, target, session_id, Clock(), sim=SimThrough(target))

    session = get_session(db, session_id)
    assert session.status == "failed" and "gave up waiting for the sim server to start" in session.message
    assert target.stops == 0 and "credits" not in session.message and "Brev" not in session.message


def test_one_target_at_a_time_and_the_message_says_how_to_free_it(db, both, config, spawned_sessions):
    a_session(db, status="ready", instance="spark1", backend="gb10")

    with pytest.raises(ComputeBusyError, match="The GB10 is connected: disconnect it before starting another target"):
        start_session(db, both, MockCompute(config.data_dir / "m.json"), INSTANCE)


def test_disconnecting_the_gb10_says_disconnecting(db, both, spawned_sessions):
    a_session(db, status="ready", instance="spark1", backend="gb10")

    assert stop_session(db, both).message == "Disconnecting"


def test_the_session_process_builds_the_client_for_the_sessions_backend(db, both, monkeypatch):
    session_id = a_session(db, status="starting", instance="spark1", backend="gb10")
    built, ran = [], []
    monkeypatch.setattr(compute_worker, "load_config", lambda: both)
    monkeypatch.setattr(
        compute_worker, "create_compute_client", lambda backend, config, data_dir: built.append(backend) or MockCompute(data_dir / "x.json")
    )
    monkeypatch.setattr(compute_worker, "run_session", lambda db, config, client, sim, sid: ran.append(sid))

    compute_worker.main([str(session_id)])

    assert (built, ran) == (["gb10"], [session_id])
