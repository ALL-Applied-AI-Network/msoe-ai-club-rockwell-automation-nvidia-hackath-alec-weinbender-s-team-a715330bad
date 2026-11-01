import cadquery as cq
import pytest

from api.clients.sim import MockSim
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.error_model import ErrorModel
from api.models.evaluation import EVAL_FINALISTS, STEP_CELL, STEP_FINGERS, STEP_PART, EvaluationSpec
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.services import cell_profiles, evaluations, fingers, jobs, parts, qualifications, results
from api.services.optimizer import run_job


class _CountingSim(MockSim):
    """The mock, counting requests; after `cancel_after` of them it asks the job to stop, as the UI's cancel does."""

    def __init__(self, cancel_after: int | None = None, cancel=None):
        self.requests, self.cancel_after, self.cancel = 0, cancel_after, cancel

    def run_batch(self, part, fingers, offsets, settings):
        self.requests += 1
        if self.cancel_after is not None and self.requests == self.cancel_after:
            self.cancel()
        return super().run_batch(part, fingers, offsets, settings)


def spec_for(e, **changes) -> EvaluationSpec:
    return EvaluationSpec(**{"part_id": e.part_id, "cell_profile_id": e.profile_id, **changes})


def test_every_planned_finger_is_ranked_with_its_best_grasp(evaluated):
    ranking = evaluations.ranking(evaluated.db, evaluated.job_id)

    assert ranking.final and not ranking.rescored and ranking.sim_backend == "mock"
    ranked = ranking.fingers
    assert {f.finger_id for f in ranked} == {evaluated.stock_id, evaluated.generated_id, evaluated.uploaded_id}
    assert [f.rank for f in ranked] == [1, 2, 3]
    assert [f.success for f in ranked] == sorted((f.success for f in ranked), reverse=True)
    plan = evaluations.jobs.get_job(evaluated.db, evaluated.job_id).plan
    for finger in ranked:
        assert finger.stage == "final", "three fingers: every one is a finalist"
        (best,) = finger.best
        assert best.pose_key == "p0" and best.stage == "final" and finger.n_grasps == plan.final_grid.size
        assert finger.success == pytest.approx(best.success)
        assert len(finger.grasps) == len(plan.poses[0].grasps)
        assert set(finger.curve) == {"0.5", "1", "2", "3", "4", "5"}
    stock = next(f for f in ranked if f.source == "stock")
    assert stock.best[0].tip_height_mm is None, "the stock fingers grip by the sim's own rule"
    assert any("flat table" in w for w in ranking.warnings)


def test_finishing_writes_each_fingers_prediction_on_the_part(evaluated):
    ranking = evaluations.ranking(evaluated.db, evaluated.job_id)
    found = {q.finger_id: q for q in qualifications.list_qualifications(evaluated.db, part_id=evaluated.part_id)}

    assert set(found) == {f.finger_id for f in ranking.fingers}
    for finger in ranking.fingers:
        prediction = found[finger.finger_id].prediction
        assert prediction.job_id == evaluated.job_id and prediction.sim_backend == "mock" and prediction.stage == "final"
        assert prediction.success == pytest.approx(finger.success)
        assert found[finger.finger_id].status == "simulated" and found[finger.finger_id].history == []


def test_a_rescore_reranks_from_the_stored_outcomes(evaluated):
    own = evaluations.ranking(evaluated.db, evaluated.job_id)
    tight = evaluations.ranking(evaluated.db, evaluated.job_id, error=ErrorModel(preset="custom", sigma_mm=0.5, sigma_deg=1.0))

    assert tight.rescored and not own.rescored
    by_id = {f.finger_id: f for f in own.fingers}
    assert any(f.success != pytest.approx(by_id[f.finger_id].success) for f in tight.fingers)
    assert all(f.success >= by_id[f.finger_id].success - 1e-9 for f in tight.fingers), "a tighter error can't hurt"
    assert [f.n_grasps for f in tight.fingers] == [by_id[f.finger_id].n_grasps for f in tight.fingers]


def test_a_finger_that_cant_grip_is_ruled_out_and_never_simulated(evaluated_copy, cad):
    e = evaluated_copy
    path = e.config.data_dir / "wide.step"
    cq.exporters.export(cq.Workplane("XY").box(12, 80, 76).translate((6, 0, 38)), str(path))  # 80 mm across: past the free space
    wide = fingers.create_finger(e.db, e.config, cad, path.name, path.read_bytes(), cell_profile_id=e.profile_id)

    plan = evaluations.plan_evaluation(e.db, e.config, spec_for(e)).plan

    mine = [r for r in plan.rejections if r.finger_id == wide.id]
    assert mine and all("outside the space" in " ".join(r.reasons) for r in mine)
    assert plan.totals.simulated == plan.totals.combinations - len(mine)
    assert any(wide.code in w and "scores 0" in w for w in plan.warnings)
    job = jobs.create_job(e.db, e.config, spec_for(e), start=False)
    run_job(e.db, job.id, sim=MockSim(), cad=cad, outputs_dir=e.config.outputs_dir)
    assert not [t for t in evaluations.load_trials(e.db, job.id) if t.finger_id == wide.id]
    ranked = next(f for f in evaluations.ranking(e.db, job.id).fingers if f.finger_id == wide.id)
    assert ranked.success == 0 and ranked.best == [] and ranked.rank == len(plan.fingers)
    assert all(g.success is None and g.reasons for g in ranked.grasps)


def test_only_the_top_fingers_and_stock_get_the_final_test(evaluated_copy, cad):
    e = evaluated_copy
    for i in range(EVAL_FINALISTS):  # three more uploads: five fingers besides stock
        path = e.config.data_dir / f"flat{i}.step"
        cq.exporters.export(cq.Workplane("XY").box(12, 6 + 2 * i, 76).translate((6, 0, 38)), str(path))
        fingers.create_finger(e.db, e.config, cad, path.name, path.read_bytes(), cell_profile_id=e.profile_id)
    job = jobs.create_job(e.db, e.config, spec_for(e), start=False)

    run_job(e.db, job.id, sim=MockSim(), cad=cad, outputs_dir=e.config.outputs_dir)

    finals = {t.finger_id for t in evaluations.load_trials(e.db, job.id, "final")}
    assert e.stock_id in finals and len(finals) == EVAL_FINALISTS + 1
    ranked = evaluations.ranking(e.db, job.id).fingers
    assert {f.finger_id for f in ranked if f.stage == "final"} == finals


def test_a_cancelled_evaluation_resumes_without_redoing_its_requests(evaluated_copy, cad):
    e = evaluated_copy
    job = jobs.create_job(e.db, e.config, spec_for(e), start=False)
    groups = sum(len(p.grasps) for p in job.plan.poses)
    assert groups >= 2

    first = _CountingSim(cancel_after=1, cancel=lambda: jobs.cancel_job(e.db, job.id))
    run_job(e.db, job.id, sim=first, cad=cad, outputs_dir=e.config.outputs_dir)
    assert jobs.get_job(e.db, job.id).status == "cancelled" and first.requests == 1
    done_first = evaluations.load_trials(e.db, job.id, "search")

    jobs.update_job(e.db, job.id, cancel_requested=0)
    second = _CountingSim()
    run_job(e.db, job.id, sim=second, cad=cad, outputs_dir=e.config.outputs_dir)

    resumed = jobs.get_job(e.db, job.id)
    assert resumed.status == "done"
    searched = evaluations.load_trials(e.db, job.id, "search")
    assert {(t.finger_id, t.pose_key, t.grasp_key) for t in searched} >= {(t.finger_id, t.pose_key, t.grasp_key) for t in done_first}
    assert len(searched) == len({(t.finger_id, t.pose_key, t.grasp_key) for t in searched}), "no request ran twice"
    assert second.requests < groups + len(job.plan.fingers), "the finished request wasn't sent again"
    assert resumed.n_done == len(evaluations.load_trials(e.db, job.id))


def test_planning_collects_what_blocks_it_with_the_step_that_fixes_it(evaluated_copy, cad, shapes, step_file):
    e = evaluated_copy
    other = cell_profiles.create_profile(e.db, "Other cell", DEFAULT_PROFILE)
    no_mass = parts.create_part(e.db, e.config, cad, "cube.step", step_file(shapes["cube"]), None)

    def steps(spec):
        plan = evaluations.plan_evaluation(e.db, e.config, spec).plan
        assert plan.blocked == [b.reason for b in plan.blockers]
        return [b.step for b in plan.blockers]

    assert steps(spec_for(e)) == []
    assert steps(spec_for(e, part_id="nope")) == [STEP_PART]
    assert steps(spec_for(e, part_id=no_mass.id)) == [STEP_PART]
    assert steps(spec_for(e, cell_profile_id=999)) == [STEP_CELL]
    assert steps(spec_for(e, finger_ids=["nope"])) == [STEP_FINGERS]
    assert steps(spec_for(e, cell_profile_id=other.id)) == [], "the new cell's installed fingers are enough"
    assert steps(spec_for(e, finger_ids=[])) == [STEP_FINGERS], "no fingers chosen"
    assert steps(spec_for(e, cell_profile_id=other.id, finger_ids=[e.uploaded_id])) == [STEP_FINGERS], "a finger for another cell"


def test_only_the_chosen_fingers_are_tried(evaluated_copy):
    e = evaluated_copy

    def tried(finger_ids):
        return [f.finger_id for f in evaluations.plan_evaluation(e.db, e.config, spec_for(e, finger_ids=finger_ids)).plan.fingers]

    assert tried([e.uploaded_id]) == [e.uploaded_id]
    assert tried([e.stock_id]) == [e.stock_id], "the installed fingers alone"
    assert tried([e.uploaded_id, e.stock_id]) == [e.stock_id, e.uploaded_id]


def test_an_archived_finger_is_left_out_of_new_evaluations(evaluated_copy):
    e = evaluated_copy
    fingers.update_finger(e.db, e.uploaded_id, {"archived": True})

    plan = evaluations.plan_evaluation(e.db, e.config, spec_for(e)).plan

    assert e.uploaded_id not in {f.finger_id for f in plan.fingers}


def test_a_locked_grasp_is_the_only_one_tried_in_its_pose(evaluated_copy):
    e = evaluated_copy
    spec = spec_for(e, poses=[{"pose": 0, "grasp": GraspChoice(angle_deg=0)}])

    plan = evaluations.plan_evaluation(e.db, e.config, spec).plan

    (pose,) = plan.poses
    assert [g.grasp.angle_deg for g in pose.grasps] == [0]


def test_the_cells_grasp_accuracy_fills_a_spec_without_one(evaluated_copy):
    e = evaluated_copy
    cheap = DEFAULT_PROFILE.model_copy(update={"grasp_accuracy": ErrorModel.from_preset("cheap")})
    version = cell_profiles.update_profile(e.db, e.profile_id, cheap)
    grasp = parts.propose_grasps(e.db, e.part_id, cheap).candidates[0]

    evaluation = jobs.create_job(e.db, e.config, spec_for(e, cell_profile_id=version.id), start=False)
    generation = jobs.create_job(
        e.db,
        e.config,
        JobSpec(part_id=e.part_id, cell_profile_id=version.id, grasp=GraspChoice(angle_deg=grasp.angle_deg), budget=8),
        start=False,
    )
    own = jobs.create_job(e.db, e.config, spec_for(e, cell_profile_id=version.id, error=ErrorModel.from_preset("calibrated")), start=False)

    assert evaluation.spec.error.preset == "cheap" and generation.spec.error.preset == "cheap"
    assert own.spec.error.preset == "calibrated", "a spec's own accuracy wins"


def test_generate_spec_starts_a_generation_job_on_the_same_part_and_grasp(evaluated):
    ranking = evaluations.ranking(evaluated.db, evaluated.job_id)
    best = ranking.fingers[0]

    spec = evaluations.generate_spec(evaluated.db, evaluated.job_id, finger_id=best.finger_id)

    assert spec.kind == "generation" and spec.part_id == evaluated.part_id and spec.name == "cube - new finger"
    (pose,) = spec.poses
    assert pose.pose == 0 and pose.grasp.angle_deg == best.best[0].angle_deg
    assert jobs.plan_spec(evaluated.db, evaluated.config, spec).plan.blockers == []
    with pytest.raises(fingers.FingerNotFoundError):
        evaluations.generate_spec(evaluated.db, evaluated.job_id, finger_id="nope")


def test_each_kind_refuses_the_others_results(evaluated):
    with pytest.raises(evaluations.WrongJobKindError):
        evaluations.ranking(evaluated.db, evaluated.generation_job_id)
    with pytest.raises(results.NotAGenerationJobError):
        results.results(evaluated.db, evaluated.job_id)


def test_an_evaluation_card_shows_its_best_finger_and_the_stock_fingers(evaluated):
    card = jobs.job_card(evaluated.db, evaluated.job_id)
    ranked = evaluations.ranking(evaluated.db, evaluated.job_id).fingers

    assert card.kind == "evaluation" and card.status == "done"
    assert card.winner.label == ranked[0].code and card.winner.success == pytest.approx(ranked[0].success)
    assert card.stock.label == next(f.code for f in ranked if f.source == "stock")
    assert [c.kind for c in jobs.job_cards(evaluated.db, kind="generation")] == ["generation"]


def test_a_batch_makes_one_evaluation_per_part_or_none(evaluated_copy, cad, shapes, step_file):
    e = evaluated_copy
    bar = parts.create_part(e.db, e.config, cad, "bar.step", step_file(shapes["bar"], "bar.step"), None)
    parts.update_part(e.db, bar.id, {"material": "pla"})
    no_mass = parts.create_part(e.db, e.config, cad, "cube.step", step_file(shapes["cube"]), None)
    before = len(jobs.list_jobs(e.db))

    with pytest.raises(jobs.JobBlockedError) as blocked:
        jobs.create_evaluations(e.db, e.config, spec_for(e), [e.part_id, no_mass.id], start=False)
    assert all(b.reason.startswith("cube.step: ") for b in blocked.value.blockers)
    assert len(jobs.list_jobs(e.db)) == before

    made = jobs.create_evaluations(e.db, e.config, spec_for(e), [e.part_id, bar.id], start=False)
    assert [j.part_id for j in made] == [e.part_id, bar.id] and all(j.kind == "evaluation" for j in made)
    assert made[0].batch_id is not None and made[0].batch_id == made[1].batch_id
    assert [c.id for c in jobs.job_cards(e.db, batch_id=made[0].batch_id)] == [j.id for j in reversed(made)]


def test_a_second_evaluation_moves_the_earlier_prediction_to_history(evaluated_copy, cad):
    e = evaluated_copy
    job = jobs.create_job(e.db, e.config, spec_for(e), start=False)
    run_job(e.db, job.id, sim=MockSim(), cad=cad, outputs_dir=e.config.outputs_dir)

    (q,) = qualifications.list_qualifications(e.db, finger_id=e.uploaded_id, part_id=e.part_id)

    assert q.prediction.job_id == job.id and [p.job_id for p in q.history] == [e.job_id]


def test_duplicating_an_evaluation_gives_its_spec_back(evaluated):
    spec = jobs.duplicate_job(evaluated.db, evaluated.job_id)

    assert spec.kind == "evaluation" and spec.part_id == evaluated.part_id and spec.name.endswith("(copy)")


def test_the_design_export_leaves_evaluation_jobs_out(evaluated):
    from api.services import export

    rows = export.trial_rows(evaluated.db)

    assert rows and {r["job_id"] for r in rows} == {evaluated.generation_job_id}
    assert export.trial_rows(evaluated.db, evaluated.job_id) == []


def test_an_evaluation_job_has_no_designs_to_print_or_test(evaluated):
    from api.services import printed_fingers

    with pytest.raises(printed_fingers.JobNotDoneError, match="evaluation job"):
        printed_fingers.done_job(evaluated.db, evaluated.job_id)
