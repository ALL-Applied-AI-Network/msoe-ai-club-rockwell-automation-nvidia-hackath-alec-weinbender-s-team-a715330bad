import datetime

import pytest

from api.db.tables import TrialRow
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec, PoseGrasp
from api.services import jobs, parts


@pytest.fixture
def cube(db, config, cad, shapes, step_file):
    """cube(**changes) -> a 10 mm cube's PartRecord, uploaded as a STEP, in PLA, standing (pose 0), with `changes`."""

    def create(**changes):
        record = parts.create_part(db, config, cad, "cube.step", step_file(shapes["cube"], "cube.step"), None)
        return parts.update_part(db, record.id, {"material": "pla", "pose": 0, **changes})

    return create


def spec_for(part_id: str, profile_id: int, **changes) -> JobSpec:
    return JobSpec(**{"part_id": part_id, "cell_profile_id": profile_id, "grasp": GraspChoice(angle_deg=0), "budget": 14, **changes})


def test_a_ready_part_plans_without_blockers(db, config, profile_id, cube):
    record = cube()

    planned = jobs.plan_spec(db, config, spec_for(record.id, profile_id))

    assert planned.plan.blockers == [] and planned.plan.blocked == []
    assert planned.part.shape == "box" and planned.part.extent_mm == pytest.approx((10, 10, 10))
    assert (planned.record.id, planned.profile.id) == (record.id, profile_id)
    assert [s.key for s in planned.plan.searches] == ["vpad"] and planned.plan.sim_backend == "mock"
    assert planned.plan.grip_force_n is None  # neither the default profile nor the part sets one


def test_every_blocker_names_the_step_that_fixes_it(db, config, profile_id, cad, shapes, step_file, cube):
    fresh = parts.create_part(db, config, cad, "cube.step", step_file(shapes["cube"]), None)
    no_pose = parts.update_part(db, parts.create_part(db, config, cad, "c.step", step_file(shapes["cube"]), None).id, {"material": "pla"})
    ready = cube()

    def steps(spec: JobSpec) -> list[int]:
        plan = jobs.plan_spec(db, config, spec).plan
        assert plan.blocked == [b.reason for b in plan.blockers]
        return [b.step for b in plan.blockers]

    assert steps(spec_for(fresh.id, profile_id)) == [1, 2]  # no material, so no mass; no resting pose
    assert steps(spec_for(no_pose.id, profile_id)) == [2]
    assert steps(spec_for("no-such-part", profile_id)) == [1]
    assert steps(spec_for(ready.id, 999)) == [4]
    assert steps(spec_for(ready.id, profile_id, grasp=GraspChoice(angle_deg=0, grip_height_mm=20))) == [5]  # above the cube
    assert steps(spec_for(cube(clearance_mm=0.0).id, profile_id)) == [6]  # no pad fits beside it


def test_the_grip_force_is_the_lesser_of_the_cells_and_the_parts(db, config, profile_id, cube):
    record = cube(max_grip_force_n=4.0, fragile=True)

    assert jobs.plan_spec(db, config, spec_for(record.id, profile_id)).plan.grip_force_n == 4.0
    fragile = cube(fragile=True)
    plan = jobs.plan_spec(db, config, spec_for(fragile.id, profile_id)).plan
    assert plan.grip_force_n is None and any("fragile" in w for w in plan.warnings)


def test_the_time_estimate_is_measured_then_configured_then_unknown(db, config, profile_id, cube, spawned):
    record = cube()

    assert jobs.throughput(db, config, "mock").source == "unknown"
    config.sim.grasps_per_s = 50.0
    assert jobs.throughput(db, config, "mock").model_dump() == {"seconds": None, "grasps_per_s": 50.0, "source": "configured"}
    job = jobs.create_job(db, config, spec_for(record.id, profile_id))
    with db.session() as s:
        for number, duration in enumerate((1.0, 2.0, 4.0, 0.0)):  # 0: a design that wasn't simulated
            s.add(_trial(job.id, number, duration))

    estimate = jobs.throughput(db, config, "mock")
    assert (estimate.source, estimate.grasps_per_s) == ("measured", 81 / 2.0)
    assert jobs.throughput(db, config, "isaac").source == "configured"  # another backend's runs don't count
    plan = jobs.plan_spec(db, config, spec_for(record.id, profile_id)).plan
    assert plan.estimate.seconds == pytest.approx(plan.totals.total_grasps / (81 / 2.0))


def test_creating_a_job_stores_what_it_runs_with_and_starts_its_worker(db, config, profile_id, cube, spawned):
    record = cube(max_grip_force_n=6.0)

    job = jobs.create_job(db, config, spec_for(record.id, profile_id))

    assert spawned == [(job.id,)]
    assert (job.experiment_id, job.status, job.sim_backend) == ("EXP-0001", "queued", "mock")
    assert job.name == f"cube_{datetime.date.today().isoformat()}" and job.spec.name == job.name
    assert job.part.shape == "box" and job.plan.grip_force_n == 6.0
    totals = job.plan.totals
    assert job.n_total == totals.search_designs + totals.final_designs == 14 + 2 + 3 + 2
    assert job.n_rounds == totals.rounds and (job.n_done, job.round) == (0, 0)
    second = jobs.create_job(db, config, spec_for(record.id, profile_id, name="  my   cube  "))
    assert (second.experiment_id, second.name) == ("EXP-0002", "my cube")


def test_a_blocked_spec_is_refused_with_its_first_step(db, config, profile_id, cad, shapes, step_file, spawned):
    record = parts.create_part(db, config, cad, "cube.step", step_file(shapes["cube"]), None)

    with pytest.raises(jobs.JobBlockedError) as raised:
        jobs.create_job(db, config, spec_for(record.id, profile_id))

    assert raised.value.failed_step == 1 and [b.step for b in raised.value.blockers] == [1, 2]
    assert jobs.list_jobs(db) == [] and spawned == []


def test_a_taken_experiment_number_is_retried(db, config, profile_id, cube, spawned, monkeypatch):
    record = cube()
    jobs.create_job(db, config, spec_for(record.id, profile_id))
    real, calls = jobs._max_experiment_number, []

    def stale(session):  # another job took the number between our read and our insert
        calls.append(1)
        return 0 if len(calls) == 1 else real(session)

    monkeypatch.setattr(jobs, "_max_experiment_number", stale)

    assert jobs.create_job(db, config, spec_for(record.id, profile_id)).experiment_id == "EXP-0002"
    assert len(calls) == 2


def test_duplicated_from_must_be_a_job(db, config, profile_id, cube, spawned):
    record = cube()
    first = jobs.create_job(db, config, spec_for(record.id, profile_id))

    assert jobs.create_job(db, config, spec_for(record.id, profile_id), duplicated_from=first.id).duplicated_from == first.id
    with pytest.raises(jobs.JobInputError, match="duplicated_from"):
        jobs.create_job(db, config, spec_for(record.id, profile_id), duplicated_from="nope")


def test_jobs_list_newest_first_and_filter(db, config, profile_id, cube, spawned):
    a, b = cube(), cube()
    first = jobs.create_job(db, config, spec_for(a.id, profile_id))
    second = jobs.create_job(db, config, spec_for(b.id, profile_id))
    jobs.update_job(db, second.id, status="done", sim_backend="isaac")

    assert [j.id for j in jobs.list_jobs(db)] == [second.id, first.id]
    assert [j.id for j in jobs.list_jobs(db, part_id=a.id)] == [first.id]
    assert [j.id for j in jobs.list_jobs(db, status="done")] == [second.id]
    assert [j.id for j in jobs.list_jobs(db, backend="mock")] == [first.id]
    assert jobs.list_jobs(db, status="failed") == []


def test_cards_show_progress_and_a_failure_line(db, config, profile_id, cube, spawned):
    job = jobs.create_job(db, config, spec_for(cube().id, profile_id))
    jobs.update_job(db, job.id, status="failed", failure="sim: can't reach the sim server", failed_step=None, round=2, n_done=7)

    card = jobs.job_card(db, job.id)

    assert (card.experiment_id, card.part_name, card.task_kind, card.sim_backend) == ("EXP-0001", "cube.step", "drop", "mock")
    assert (card.status, card.failure, card.round, card.n_rounds, card.n_done, card.n_total) == (
        "failed",
        "sim: can't reach the sim server",
        2,
        4,
        7,
        21,
    )
    assert (card.winner, card.stock, card.physical_badge) == (None, None, "none")
    assert jobs.job_cards(db) == [card]


def test_rename_keeps_the_experiment_id(db, config, profile_id, cube, spawned):
    job = jobs.create_job(db, config, spec_for(cube().id, profile_id))

    renamed = jobs.rename_job(db, job.id, "  vial cap, groove test ")

    assert (renamed.name, renamed.experiment_id) == ("vial cap, groove test", job.experiment_id)
    with pytest.raises(jobs.JobInputError):
        jobs.rename_job(db, job.id, "   ")
    with pytest.raises(jobs.JobNotFoundError):
        jobs.rename_job(db, "nope", "x")


def test_duplicate_returns_a_renamed_spec_and_starts_nothing(db, config, profile_id, cube, spawned):
    job = jobs.create_job(db, config, spec_for(cube().id, profile_id, seed=7))

    spec = jobs.duplicate_job(db, job.id)

    assert spec.name == f"{job.name} (copy)" and spec.seed == 7 and spec.part_id == job.part_id
    assert len(jobs.list_jobs(db)) == 1 and spawned == [(job.id,)]


def test_cancel_and_resume(db, config, profile_id, cube, spawned):
    job = jobs.create_job(db, config, spec_for(cube().id, profile_id))

    jobs.cancel_job(db, job.id)
    assert jobs.get_job(db, job.id).cancel_requested == 1
    with pytest.raises(jobs.JobNotResumableError):
        jobs.resume_job(db, config, job.id)  # still queued
    jobs.update_job(db, job.id, status="cancelled")
    jobs.resume_job(db, config, job.id)
    assert spawned == [(job.id,), (job.id,)] and jobs.get_job(db, job.id).cancel_requested == 0
    with pytest.raises(jobs.JobNotFoundError):
        jobs.cancel_job(db, "nope")
    with pytest.raises(jobs.JobNotFoundError):
        jobs.resume_job(db, config, "nope")


def test_jobs_whose_worker_is_gone_are_marked_interrupted(db, config, profile_id, cube, spawned):
    job = jobs.create_job(db, config, spec_for(cube().id, profile_id))
    jobs.update_job(db, job.id, status="running", pid=None)

    jobs.mark_interrupted(db)

    assert jobs.get_job(db, job.id).status == "interrupted"


def _trial(job_id: str, number: int, duration: float) -> TrialRow:
    return TrialRow(
        job_id=job_id,
        number=number,
        round=0,
        search="vpad",
        grid="search",
        kind="search",
        params=None,
        success_rate=0.5,
        capture_radius_mm=None,
        n_grasps=81,
        n_success=0,
        held=[False] * 81,
        in_hand=[None] * 81,
        held_after_transport=None,
        duration=duration,
    )


@pytest.fixture
def bar(db, config, cad, shapes, step_file):
    """A 10 x 10 x 20 mm PLA bar's PartRecord, with no chosen pose: on its side (pose 0, 87%) or standing (pose 1, 13%)."""
    record = parts.create_part(db, config, cad, "bar.step", step_file(shapes["bar"], "bar.step"), None)
    return parts.update_part(db, record.id, {"material": "pla"})


def test_a_spec_with_one_grasp_plans_its_parts_chosen_pose(db, config, profile_id, cube):
    record = cube()

    legacy = jobs.plan_spec(db, config, spec_for(record.id, profile_id))
    poses = [PoseGrasp(pose=0, grasp=GraspChoice(angle_deg=0))]
    alone = jobs.plan_spec(db, config, spec_for(record.id, profile_id, grasp=None, poses=poses))

    (pose,) = legacy.plan.poses
    assert (pose.key, pose.label, pose.choice, pose.weight, pose.part) == ("p0", "standing", None, 1.0, legacy.part)
    assert legacy.plan.model_dump(exclude={"poses"}) == alone.plan.model_dump(exclude={"poses"}) and alone.plan.poses[0].choice == 0


def test_several_poses_are_ordered_by_likelihood_and_weighted(db, config, profile_id, bar):
    poses = [PoseGrasp(pose=1, grasp=GraspChoice(angle_deg=0)), PoseGrasp(pose=0, grasp=GraspChoice(angle_deg=90))]

    planned = jobs.plan_spec(db, config, spec_for(bar.id, profile_id, grasp=None, poses=poses))

    plan = planned.plan
    assert plan.blockers == [] and parts.get_part(db, bar.id).pose is None  # the record's chosen pose isn't needed
    assert [(p.key, p.label, p.choice, p.grasp.angle_deg) for p in plan.poses] == [("p0", "on its side", 0, 90), ("p1", "standing", 1, 0)]
    assert sum(p.weight for p in plan.poses) == pytest.approx(1) and plan.poses[0].weight == pytest.approx(0.8718, abs=1e-3)
    assert planned.part == plan.part == plan.poses[0].part and plan.poses[1].part.extent_mm == pytest.approx((10, 10, 20))
    assert plan.totals.poses == 2 and plan.grid.yaws_deg != [0]


def test_each_poses_grasp_is_checked_in_that_pose(db, config, profile_id, bar):
    def blockers(*poses: PoseGrasp) -> list[tuple[int, str]]:
        plan = jobs.plan_spec(db, config, spec_for(bar.id, profile_id, grasp=None, poses=list(poses))).plan
        return [(b.step, b.reason) for b in plan.blockers]

    high = GraspChoice(angle_deg=0, grip_height_mm=15)  # above the bar on its side, not standing

    assert blockers(PoseGrasp(pose=1, grasp=high)) == []
    assert [step for step, _ in blockers(PoseGrasp(pose=0, grasp=high), PoseGrasp(pose=1, grasp=high))] == [5]
    assert blockers(PoseGrasp(pose=0, grasp=high), PoseGrasp(pose=1, grasp=high))[0][1].startswith("grasp (on its side): ")
    assert blockers(PoseGrasp(pose=7, grasp=high)) == [(2, 'resting pose: pose must be an index from 0 to 2, or "as_authored"')]


def test_duplicating_a_spec_with_one_grasp_gives_it_its_pose(db, config, profile_id, cube, spawned):
    job = jobs.create_job(db, config, spec_for(cube().id, profile_id))

    spec = jobs.duplicate_job(db, job.id)

    assert spec.grasp is None and spec.poses == [PoseGrasp(pose=0, grasp=job.spec.grasp)]
    assert jobs.plan_spec(db, config, spec).plan.blockers == []
