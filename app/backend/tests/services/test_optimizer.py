import datetime
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import select

from api.clients.sim import MockSim, SimError, SimSettings
from api.db.tables import ResultRow, RunMetaRow, TrialRow
from api.models.family import FamilyChoice
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec, PoseGrasp
from api.models.outcome import Outcomes
from api.models.task import Task
from api.services import jobs, optimizer, parts

CUBE_LOCKS = {"pad_width_mm": 12.0, "slack_mm": 2.0, "tip_height_mm": 3.0, "lead_in_mm": 0.0}  # a single design


class RecordingSim:
    """The mock sim, recording each request as (designs, offsets, settings). fail_on: the request (1, 2, ...) that raises
    a SimError instead; on_call(n) runs after request n is answered."""

    backend, badge, url = "mock", "mock", None

    def __init__(self, fail_on: int | None = None, on_call=None):
        self.mock, self.fail_on, self.on_call = MockSim(), fail_on, on_call
        self.calls: list[tuple[int, int, SimSettings]] = []

    def run_batch(self, part, fingers, offsets, settings):
        self.calls.append((len(fingers), len(offsets), settings))
        if self.fail_on == len(self.calls):
            raise SimError("can't reach the sim server at http://sim:9000: connection refused")
        out = self.mock.run_batch(part, fingers, offsets, settings)
        if self.on_call:
            self.on_call(len(self.calls))
        return out

    def describe(self):
        return {}

    def close(self):
        pass

    @property
    def designs(self) -> list[int]:
        return [n for n, _, _ in self.calls]


class HoldsEverythingSim(RecordingSim):
    """Every design holds at every offset, centred: every design scores the same."""

    def run_batch(self, part, fingers, offsets, settings):
        self.calls.append((len(fingers), len(offsets), settings))
        n = len(offsets)
        after = [True] * n if settings.transport else None
        return [Outcomes(held=[True] * n, in_hand=[(0.0, 0.0, 0.0, 0.0, 0.0)] * n, held_after_transport=after) for _ in fingers]


@pytest.fixture
def cube_job(db, config, cad, shapes, step_file, profile_id, spawned):
    """cube_job(part_changes={}, **spec_changes) -> a queued job for a 10 mm PLA cube standing on the table."""

    def create(part_changes: dict | None = None, **spec_changes):
        record = parts.create_part(db, config, cad, "cube.step", step_file(shapes["cube"], "cube.step"), None)
        parts.update_part(db, record.id, {"material": "pla", "pose": 0, **(part_changes or {})})
        values = {"part_id": record.id, "cell_profile_id": profile_id, "grasp": GraspChoice(angle_deg=0), "budget": 14}
        return jobs.create_job(db, config, JobSpec(**values | spec_changes))

    return create


def run(db, config, cad, job_id: str, sim) -> None:
    optimizer.run_job(db, job_id, sim=sim, cad=cad, outputs_dir=config.outputs_dir)


def trials(db, job_id: str, grid: str | None = None) -> list[TrialRow]:
    query = select(TrialRow).where(TrialRow.job_id == job_id).order_by(TrialRow.number)
    with db.session() as s:
        return list(s.scalars(query if grid is None else query.where(TrialRow.grid == grid)))


def test_a_cube_runs_through_bo_rounds_to_labelled_finals_and_d1_files(db, config, cad, cube_job):
    job = cube_job()  # 4 free parameters: 12 Sobol designs, then two GP rounds of one
    sim = RecordingSim()

    run(db, config, cad, job.id, sim)

    done = jobs.get_job(db, job.id)
    assert done.status == "done", done.error
    assert sim.designs == [2 + 12, 1, 1, 3 + 2] and [n for _, n, _ in sim.calls] == [243, 243, 243, 963]
    searched, final = trials(db, job.id, "search"), trials(db, job.id, "final")
    assert Counter(t.round for t in searched) == {0: 14, 1: 1, 2: 1}
    assert sorted(t.label for t in final) == ["D1", "D2", "D3", "IMP", "STOCK"]
    by_label = {t.label: t for t in final}
    designs = [by_label[label] for label in ("D1", "D2", "D3")]
    assert [t.success_rate for t in designs] == sorted((t.success_rate for t in designs), reverse=True)
    assert {t.round for t in final} == {3} and all(t.n_grasps == 963 for t in final)
    assert (by_label["STOCK"].kind, by_label["IMP"].kind, by_label["D1"].search) == ("stock", "imprint", "vpad")
    assert (done.round, done.n_rounds, done.n_done, done.n_total) == (4, 4, 21, 21)
    assert (done.best_value, done.best_trial) == (by_label["D1"].success_rate, by_label["D1"].number) and done.finished

    with db.session() as s:
        result = s.get(ResultRow, job.id)
        assert (result.label, result.trial_number, result.predicted_success) == ("D1", by_label["D1"].number, by_label["D1"].success_rate)
        files = {key: Path(path) for key, path in result.cad_files.items()}
        checks, pose = result.checks, result.grasp_pose
    stem = f"cube_{datetime.date.today().isoformat()}_EXP-0001_D1_MOCK"
    assert {key: path.name for key, path in files.items()} == {
        "step": f"{stem}.step",
        "stl_left": f"{stem}_L.stl",
        "stl_right": f"{stem}_R.stl",
        "print_sheet": f"{stem}_print_sheet.pdf",
    }
    assert files["step"].read_bytes().startswith(b"ISO-10303-21") and files["print_sheet"].read_bytes().startswith(b"%PDF")
    assert all(path.stat().st_size > 0 and path.parent == config.outputs_dir / job.id for path in files.values())
    assert all(check["ok"] for check in checks if check["blocking"])
    assert pose["grasp_angle_deg"] == 0 and pose["grasp_centre_mm"] == [0.0, 0.0] and "tip_height_mm" in pose


def test_the_vial_cap_runs_to_done(finished_job):
    db, job_id = finished_job.db, finished_job.job_id

    searched, final = trials(db, job_id, "search"), trials(db, job_id, "final")

    assert Counter(t.round for t in searched) == {0: 2 + 16, 1: 1, 2: 1}  # 6 free parameters: 16 Sobol designs
    assert sorted(t.label for t in final) == ["D1", "D2", "D3", "IMP", "STOCK"]
    assert all(t.n_grasps == 321 for t in final) and all(t.n_grasps == 81 for t in searched)  # round from above: no yaw
    with db.session() as s:
        files = s.get(ResultRow, job_id).cad_files
    assert sorted(files) == ["print_sheet", "step", "stl_left", "stl_right"] and all(Path(p).exists() for p in files.values())


def test_every_request_carries_the_grip_force_and_transport(db, config, cad, cube_job):
    job = cube_job({"max_grip_force_n": 3.0}, families=[FamilyChoice(locks=CUBE_LOCKS)], task=Task(transport="fast"))
    sim = RecordingSim()

    run(db, config, cad, job.id, sim)

    assert jobs.get_job(db, job.id).status == "done"
    assert sim.designs == [3, 3]  # round 0: stock, imprint, the locked design; then the final test
    assert [settings for _, _, settings in sim.calls] == [SimSettings(grip_force_n=3.0, transport="fast")] * 2
    assert all(t.held_after_transport is not None for t in trials(db, job.id))
    assert {t.kind for t in trials(db, job.id, "search")} == {"stock", "imprint", "locked"}


def test_designs_failing_the_geometry_checks_are_not_simulated(db, config, cad, cube_job, monkeypatch):
    job = cube_job(families=[FamilyChoice(locks=CUBE_LOCKS)])
    monkeypatch.setattr(optimizer, "problems", lambda *args, **kwargs: ["the finger reaches outside the free space"])
    sim = RecordingSim()

    run(db, config, cad, job.id, sim)

    assert sim.designs == [1, 1]  # only the stock fingers, which are the robot's own
    dropped = [t for t in trials(db, job.id) if t.kind != "stock"]
    assert dropped and all(not any(t.held) and t.duration == 0 and t.success_rate == 0 for t in dropped)


def test_a_cancel_stops_between_rounds_and_a_resume_redoes_none(db, config, cad, cube_job):
    job = cube_job()
    first = RecordingSim(on_call=lambda n: jobs.cancel_job(db, job.id))

    run(db, config, cad, job.id, first)

    assert jobs.get_job(db, job.id).status == "cancelled" and first.designs == [14]
    before = [(t.number, t.params) for t in trials(db, job.id)]
    jobs.resume_job(db, config, job.id)
    second = RecordingSim()
    run(db, config, cad, job.id, second)

    assert jobs.get_job(db, job.id).status == "done" and second.designs == [1, 1, 5]
    assert [(t.number, t.params) for t in trials(db, job.id, "search")][: len(before)] == before
    assert Counter(t.round for t in trials(db, job.id, "search")) == {0: 14, 1: 1, 2: 1}


def test_a_failed_round_stores_a_failure_line_and_is_the_only_one_redone(db, config, cad, cube_job):
    job = cube_job()

    run(db, config, cad, job.id, RecordingSim(fail_on=2))

    failed = jobs.get_job(db, job.id)
    assert failed.status == "failed" and failed.failed_step is None
    assert failed.failure == "sim: can't reach the sim server at http://sim:9000: connection refused"
    assert "SimError" in failed.error and len(trials(db, job.id)) == 14
    jobs.resume_job(db, config, job.id)
    sim = RecordingSim()
    run(db, config, cad, job.id, sim)
    assert jobs.get_job(db, job.id).status == "done" and sim.designs == [1, 1, 5]
    assert jobs.get_job(db, job.id).failure is None


def test_a_failure_with_a_known_input_step_says_which(db, config, cad, cube_job):
    job = cube_job()
    jobs.update_job(db, job.id, cell_profile_id=999)

    run(db, config, cad, job.id, RecordingSim())

    failed = jobs.get_job(db, job.id)
    assert (failed.status, failed.failure, failed.failed_step) == ("failed", "cell profile 999 no longer exists", 4)


def test_finishing_again_replaces_the_final_test_and_a_done_job_is_left_alone(db, config, cad, cube_job):
    job = cube_job(families=[FamilyChoice(locks=CUBE_LOCKS)])
    run(db, config, cad, job.id, RecordingSim())
    jobs.update_job(db, job.id, status="interrupted")  # e.g. the worker died just after committing, before exiting
    sim = RecordingSim()

    run(db, config, cad, job.id, sim)

    assert sim.designs == [3] and jobs.get_job(db, job.id).status == "done"
    assert sorted(t.label for t in trials(db, job.id, "final")) == ["D1", "IMP", "STOCK"]
    assert len(trials(db, job.id)) == 6
    untouched = RecordingSim()
    run(db, config, cad, job.id, untouched)
    assert untouched.calls == []


@pytest.mark.filterwarnings("ignore::botorch.exceptions.warnings.InputDataWarning")  # equal scores can't be standardized
def test_a_search_that_stops_gaining_stops_on_patience(db, config, cad, cube_job):
    job = cube_job(budget=40)  # 12 Sobol designs, then batches of 4; patience 12 designs
    search = job.plan.searches[0]
    assert (search.n_initial, search.batch_size, search.patience) == (12, 4, 12)

    run(db, config, cad, job.id, HoldsEverythingSim())

    assert jobs.get_job(db, job.id).status == "done"
    assert Counter(t.round for t in trials(db, job.id, "search")) == {0: 14, 1: 4}
    with db.session() as s:
        meta = s.get(RunMetaRow, job.id).meta
    assert [(s["key"], s["designs"], s["stop_reason"]) for s in meta["searches"]] == [("vpad", 16, "patience")]


def test_the_run_metadata_records_what_the_run_used(finished_job):
    with finished_job.db.session() as s:
        meta = s.get(RunMetaRow, finished_job.job_id).meta

    assert set(meta["versions"]) == {"python", "botorch", "gpytorch", "torch", "cadquery"}
    assert "gpu" in meta and meta["seed"] == 0
    assert meta["grids"]["final"]["n_directions"] == 2 * meta["grids"]["search"]["n_directions"]
    assert meta["sim"] == {"backend": "mock", "badge": "mock", "url": None, "describe": {}}
    assert meta["cell_profile"] == {"id": finished_job.profile_id, "name": "UWM CSI cell", "version": 1}
    assert meta["plan"]["searches"][0]["key"] == "vpad" and meta["experiment_id"] == "EXP-0001"
    assert [(s["key"], s["designs"], s["stop_reason"]) for s in meta["searches"]] == [("vpad", 18, "budget")]
    assert meta["warnings"] == []  # the default profile is the twin's cell, and the mock reports no settings


def test_a_job_never_runs_on_another_sim_than_its_badge_says(db, config, cad, cube_job):
    """A resumed job keeps its badge, so finishing it on another sim would pass one sim's results off as the other's."""

    class OtherSim(MockSim):
        badge = "isaac"

    job_id = cube_job().id

    run(db, config, cad, job_id, OtherSim())

    job = jobs.get_job(db, job_id)
    assert job.status == "failed" and "runs on the mock sim" in job.failure
    assert trials(db, job_id) == []


class PoseRecordingSim(RecordingSim):
    """RecordingSim that also records the posed part's size (along the jaws, across, height) of each request."""

    def __init__(self):
        super().__init__()
        self.parts: list[tuple[float, float, float]] = []

    def run_batch(self, part, fingers, offsets, settings):
        self.parts.append(tuple(round(v, 3) for v in part.extent_mm))
        return super().run_batch(part, fingers, offsets, settings)


LYING, STANDING = (10.0, 20.0, 10.0), (10.0, 10.0, 20.0)  # the bar as each pose's grasp meets it


@pytest.fixture
def bar_job(db, config, cad, shapes, step_file, profile_id, spawned):
    """bar_job(standing_grasp=GraspChoice(angle_deg=0), **spec_changes) -> a queued job over the bar's two resting
    poses: on its side (the primary, gripped across at 90 deg) and standing."""

    def create(standing_grasp: GraspChoice | None = None, **spec_changes):
        record = parts.create_part(db, config, cad, "bar.step", step_file(shapes["bar"], "bar.step"), None)
        parts.update_part(db, record.id, {"material": "pla"})
        poses = [PoseGrasp(pose=0, grasp=GraspChoice(angle_deg=90)), PoseGrasp(pose=1, grasp=standing_grasp or GraspChoice(angle_deg=0))]
        values = {"part_id": record.id, "cell_profile_id": profile_id, "poses": poses, "budget": 14}
        return jobs.create_job(db, config, JobSpec(**values | spec_changes))

    return create


def test_every_round_sends_one_request_per_pose_and_scores_over_both(db, config, cad, bar_job):
    job = bar_job()
    sim = PoseRecordingSim()

    run(db, config, cad, job.id, sim)

    done = jobs.get_job(db, job.id)
    assert done.status == "done", done.error
    assert sim.designs == [14, 14, 1, 1, 1, 1, 5, 5] and sim.parts == [LYING, STANDING] * 4
    weights = [pose.weight for pose in done.poses]
    for trial in trials(db, job.id):
        (standing,) = trial.pose_outcomes
        assert trial.n_grasps == 2 * len(trial.held) and trial.n_success == sum(trial.held) + sum(standing.held)
        grid = done.plan.final_grid if trial.grid == "final" else done.plan.grid
        error = done.spec.error
        expected = weights[0] * grid.expected_success(trial.held, error) + weights[1] * grid.expected_success(standing.held, error)
        assert trial.success_rate == pytest.approx(expected)
    with db.session() as s:
        pose = s.get(ResultRow, job.id).grasp_pose
    assert [(p["resting_pose"], p["grasp_angle_deg"]) for p in pose["poses"]] == [("on its side", 90), ("standing", 0)]
    assert pose["poses"][1]["tip_height_mm"] > pose["poses"][0]["tip_height_mm"]  # the standing bar is twice as tall


def test_a_pose_a_design_cant_grip_scores_zero_there_and_isnt_sent(db, config, cad, bar_job):
    job = bar_job(GraspChoice(angle_deg=0, grip_height_mm=1.0))  # standing, gripped this low its top reaches every bridge
    sim = PoseRecordingSim()

    run(db, config, cad, job.id, sim)

    done = jobs.get_job(db, job.id)
    assert done.status == "done", done.error
    # Standing, only the stock fingers (the robot's own) are sent: in round 0 and the final test, and no request at all in
    # the rounds that have none
    assert list(zip(sim.parts, sim.designs, strict=True)) == [(LYING, 14), (STANDING, 1), (LYING, 1), (LYING, 1), (LYING, 5), (STANDING, 1)]
    by_kind = {}
    for trial in trials(db, job.id):
        by_kind.setdefault(trial.kind, []).append(trial)
    assert all(not any(t.pose_outcomes[0].held) for kind in ("search", "imprint") for t in by_kind[kind])
    primary = done.poses[0].weight
    for t in by_kind["search"]:
        grid = done.plan.final_grid if t.grid == "final" else done.plan.grid
        assert t.success_rate == pytest.approx(primary * grid.expected_success(t.held, done.spec.error))


def test_one_pose_runs_exactly_as_a_spec_with_one_grasp_did(db, config, cad, cube_job):
    legacy = cube_job(seed=3)
    record_id = legacy.part_id
    alone = jobs.create_job(
        db,
        config,
        legacy.spec.model_copy(update={"name": None, "grasp": None, "poses": [PoseGrasp(pose=0, grasp=legacy.spec.grasp)]}),
    )
    assert alone.part_id == record_id

    for job in (legacy, alone):
        run(db, config, cad, job.id, RecordingSim())

    first, second = trials(db, legacy.id), trials(db, alone.id)
    assert [(t.label, t.success_rate, t.capture_radius_mm, t.n_grasps, t.held) for t in first] == [
        (t.label, t.success_rate, t.capture_radius_mm, t.n_grasps, t.held) for t in second
    ]
    assert all(t.pose_outcomes is None for t in first + second)
