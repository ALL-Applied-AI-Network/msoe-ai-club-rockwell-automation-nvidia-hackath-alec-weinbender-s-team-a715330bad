import csv
import io
from collections import Counter

import pytest
from openpyxl import load_workbook

from api.clients.sim import MockSim, SimSettings
from api.db.tables import JobRow, TrialRow
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.error_model import ErrorModel
from api.models.family import VPadParams
from api.models.finger import build_finger
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.outcome import Outcomes
from api.models.part import Part
from api.models.search_plan import TimeEstimate, plan_job
from api.models.task import Task
from api.services import physical_trials, printed_fingers, test_plans

FINALS = [
    ("D1", "search", VPadParams(pad_width_mm=20, slack_mm=1, tip_height_mm=3)),
    ("D2", "search", VPadParams(pad_width_mm=8, slack_mm=0.5, tip_height_mm=3)),
    ("STOCK", "stock", None),
    ("IMP", "imprint", None),
]
BOX = Part(shape="box", width_mm=10, depth_mm=10, height_mm=10)
PER_DESIGN = 25 * 3 + 30


def add_job(db, profile_id, *, job_id="job1", number=42, status="done", part=None, task=None, error=None, selection=("D1",)) -> str:
    """A job as the optimizer leaves it, written straight to the tables: its spec, part and plan, final-grid trials
    labelled D1, D2, STOCK and IMP (their outcomes don't matter here), and a print selection."""
    part = part or Part()
    spec = JobSpec(
        name="Vial cap: first try",
        part_id="part",
        cell_profile_id=profile_id,
        grasp=GraspChoice(angle_deg=0),
        task=task or Task(),
        error=error or ErrorModel(),
    )
    plan = plan_job(
        part, spec, DEFAULT_PROFILE, sim_backend="mock", estimate=TimeEstimate(seconds=None, grasps_per_s=None, source="unknown")
    )
    job = {"id": job_id, "experiment_number": number, "name": spec.name, "status": status, "part_id": "part", "cell_profile_id": profile_id}
    with db.session() as s:
        s.add(JobRow(**job, sim_backend="mock", spec=spec, part=part, plan=plan, print_designs=list(selection)))
        for n, (label, kind, params) in enumerate(FINALS, start=1):
            outcomes = {
                "success_rate": 0.5,
                "capture_radius_mm": None,
                "n_grasps": 0,
                "n_success": 0,
                "held": [],
                "in_hand": [],
                "duration": 0,
            }
            params = params.model_dump() if params else None
            s.add(
                TrialRow(job_id=job_id, number=n, round=1, search="final", grid="final", kind=kind, label=label, params=params, **outcomes)
            )
    return job_id


class FakeSim:
    """Holds where held(dx, dy) says, the part centred in the hand except for dy; records every batch it's sent."""

    backend, badge, url = "mock", "mock", None

    def __init__(self, held=lambda dx, dy: abs(dx) < 3.5):
        self.held, self.calls = held, []

    def run_batch(self, part, fingers, offsets, settings):
        self.calls.append((fingers, offsets, settings))
        held = [self.held(o["dx"], o["dy"]) for o in offsets]
        in_hand = [(0.0, o["dy"], 0.0, 0.0, 0.0) if h else None for h, o in zip(held, offsets, strict=True)]
        return [Outcomes(held=held, in_hand=in_hand, held_after_transport=held if settings.transport else None) for _ in fingers]


class BrokenSim(FakeSim):
    def run_batch(self, part, fingers, offsets, settings):
        raise RuntimeError("sim server unreachable")


def test_a_plan_covers_the_selection_and_both_baselines(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id, selection=("D2", "D1"))

    plan = test_plans.create_test_plan(db, config, job_id, seed=11)

    assert (plan.designs, plan.seed, plan.prediction_status) == (["D2", "D1", "IMP", "STOCK"], 11, "pending")
    assert spawned == [(job_id, "predict", str(plan.id))]
    assert Counter(row.design_label for row in plan.rows) == {label: PER_DESIGN for label in plan.designs}
    assert [row.trial_id for row in plan.rows[:3]] == ["T0001", "T0002", "T0003"] and plan.rows[-1].trial_id == f"T{4 * PER_DESIGN:04d}"
    assert test_plans.get_test_plan(db, job_id, plan.id) == plan == test_plans.list_test_plans(db, job_id)[0]


def test_each_design_gets_25_pointwise_offsets_three_times_then_30_random(db, config, profile_id, spawned):
    plan = test_plans.create_test_plan(db, config, add_job(db, profile_id), seed=3)
    rows = [row for row in plan.rows if row.design_label == "D1"]

    pointwise, random = rows[:75], rows[75:]
    assert {row.kind for row in pointwise} == {"pointwise"} and {row.kind for row in random} == {"random"} and len(random) == 30
    assert [row.repeat for row in pointwise] == [1] * 25 + [2] * 25 + [3] * 25 and {row.repeat for row in random} == {1}
    assert len({row.offset for row in pointwise}) == 25 and pointwise[:25] == [r.model_copy(update={"repeat": 1}) for r in pointwise[:25]]
    assert {row.offset for row in pointwise[:25]} == {row.offset for row in pointwise[25:50]} == {row.offset for row in pointwise[50:]}
    assert {row.yaw_deg for row in rows} == {0.0}  # the vial cap is round from above


def test_counts_and_seed_are_the_requests(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id, part=BOX, error=ErrorModel(sigma_mm=2, sigma_deg=6))

    first = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=5, seed=99)
    again = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=5, seed=99)
    other = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=5, seed=100)

    offsets = [[row.offset for row in plan.rows if row.kind == "random"] for plan in (first, again, other)]
    assert len(first.rows) == 3 * (25 + 5)
    assert offsets[0] == offsets[1] != offsets[2]
    assert any(yaw != 0 for _, _, yaw in offsets[0])  # a box's yaw is drawn
    unseeded = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=5)
    assert isinstance(unseeded.seed, int) and test_plans.get_test_plan(db, job_id, unseeded.id).seed == unseeded.seed


def test_trial_ids_continue_across_plans_and_extra_trials(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    first = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=0)
    extra = physical_trials.log_trial(db, job_id, {"design_label": "D1", "offset_x_mm": 9, "offset_y_mm": 0, "outcome": "missed"})

    second = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=0)

    assert first.rows[-1].trial_id == "T0075" and extra.trial_id == "T0076"
    assert second.rows[0].trial_id == "T0077" and second.rows[-1].trial_id == "T0151"


def test_printed_fingers_fill_the_finger_id(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    printed_fingers.add_printed_finger(db, job_id, design_label="D1", side="L", material="PLA")
    printed_fingers.add_printed_finger(db, job_id, design_label="D1", side="R", material="PLA")

    plan = test_plans.create_test_plan(db, config, job_id, random_per_design=0)

    assert {row.design_label: row.finger_id for row in plan.rows} == {"D1": "EXP-0042-D1", "IMP": None, "STOCK": None}


def test_a_plan_needs_a_finished_job(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id, status="finalizing")

    with pytest.raises(printed_fingers.JobNotDoneError):
        test_plans.create_test_plan(db, config, job_id)
    with pytest.raises(test_plans.TestPlanError):
        test_plans.create_test_plan(db, config, add_job(db, profile_id, job_id="job2", number=43), pointwise_repeats=0)
    assert spawned == []


def test_the_prediction_is_the_tasks_success_from_the_mock(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    plan = test_plans.create_test_plan(db, config, job_id, seed=5)

    test_plans.predict_test_plan(db, str(plan.id), sim=MockSim())  # as the worker's argv has it

    predicted = test_plans.get_test_plan(db, job_id, plan.id)
    assert (predicted.prediction_status, predicted.prediction_error) == ("done", None)
    assert all(row.predicted is not None and row.predicted_in_tolerance is None for row in predicted.rows)  # drop: no tolerance
    d1 = [row for row in predicted.rows if row.design_label == "D1"][:25]
    finger = build_finger(Part(), printed_fingers.final_designs(db, job_id)["D1"], DEFAULT_PROFILE.gripper)
    (expected,) = MockSim().run_batch(
        Part(), [finger], [{"dx": r.offset_x_mm, "dy": r.offset_y_mm, "yaw_deg": 0.0} for r in d1], SimSettings()
    )
    assert [row.predicted for row in d1] == expected.held
    assert True in expected.held and False in expected.held


def test_each_design_is_simulated_once_at_its_unique_offsets(db, config, profile_id, spawned):
    task = Task(kind="place", offset_tolerance_mm=2.0, transport="fast")
    job_id = add_job(db, profile_id, task=task)
    plan = test_plans.create_test_plan(db, config, job_id, seed=5)
    sim = FakeSim(held=lambda dx, dy: abs(dx) < 3.5)

    test_plans.predict_test_plan(db, plan.id, sim=sim)

    assert len(sim.calls) == 3  # D1, IMP, STOCK
    assert [len(offsets) for _, offsets, _ in sim.calls] == [25 + 30] * 3
    assert sim.calls[2][0] == [None] and all(fingers[0] is not None for fingers, _, _ in sim.calls[:2])  # STOCK: the sim's own
    assert [settings for _, _, settings in sim.calls] == [SimSettings(grip_force_n=None, transport="fast")] * 3
    rows = {row.offset: row for row in test_plans.get_test_plan(db, job_id, plan.id).rows if row.design_label == "D1"}
    assert (rows[1.0, 0.0, 0.0].predicted, rows[1.0, 0.0, 0.0].predicted_in_tolerance) == (True, True)
    assert (rows[0.0, 3.0, 0.0].predicted, rows[0.0, 3.0, 0.0].predicted_in_tolerance) == (False, False)  # held, but 3 mm off
    assert (rows[6.0, 0.0, 0.0].predicted, rows[6.0, 0.0, 0.0].predicted_in_tolerance) == (False, False)  # missed


def test_a_failed_prediction_is_stored_not_raised(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    plan = test_plans.create_test_plan(db, config, job_id, random_per_design=0)

    test_plans.predict_test_plan(db, plan.id, sim=BrokenSim())
    test_plans.predict_test_plan(db, 999, sim=BrokenSim())  # no such plan: logged, not raised

    failed = test_plans.get_test_plan(db, job_id, plan.id)
    assert (failed.prediction_status, failed.prediction_error) == ("failed", "RuntimeError: sim server unreachable")
    assert all(row.predicted is None for row in failed.rows)
    again = test_plans.predict_again(db, config, job_id, plan.id)
    assert (again.prediction_status, again.prediction_error) == ("pending", None) and spawned[-1] == (job_id, "predict", str(plan.id))


def test_a_worker_that_cant_start_fails_the_prediction(db, config, profile_id, monkeypatch):
    def refuse(*args):
        raise OSError("no python")

    monkeypatch.setattr(test_plans.jobs, "spawn_worker", refuse)

    plan = test_plans.create_test_plan(db, config, add_job(db, profile_id), random_per_design=0)

    assert plan.prediction_status == "failed" and "couldn't start the prediction worker: no python" in plan.prediction_error


def test_without_a_ready_gpu_the_plan_is_kept_and_its_prediction_says_why(db, config, profile_id, spawned, monkeypatch):
    monkeypatch.setattr(config.compute, "backends", "brev")  # the app manages the GPU, and no session is up

    plan = test_plans.create_test_plan(db, config, add_job(db, profile_id), random_per_design=0)

    assert plan.prediction_status == "failed" and "choose a target in the GPU panel" in plan.prediction_error
    assert spawned == [] and test_plans.get_test_plan(db, "job1", plan.id).prediction_status == "failed"


def test_the_xlsx_has_the_columns_dropdowns_and_a_hidden_prediction(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id, task=Task(kind="insert", offset_tolerance_mm=1, tilt_tolerance_deg=5))
    plan = test_plans.create_test_plan(db, config, job_id, seed=2)
    test_plans.predict_test_plan(db, plan.id, sim=FakeSim())

    name, content = test_plans.plan_xlsx(db, job_id, plan.id)

    sheet = load_workbook(io.BytesIO(content)).active
    assert name == "Vial-cap-first-try_EXP-0042_test-plan-1.xlsx"
    assert tuple(cell.value for cell in sheet[1]) == test_plans.COLUMNS and sheet.max_row == 1 + 3 * PER_DESIGN
    assert [cell.value for cell in sheet[2]][:10] == ["T0001", "EXP-0042", "D1", None, 0, 0, 0, 1, "yes", None]
    assert sheet.column_dimensions["I"].hidden and not sheet.column_dimensions["J"].hidden
    rules = {rule.formula1: str(rule.sqref) for rule in sheet.data_validations.dataValidation}
    assert rules == {'"held,missed,skipped"': f"J2:J{1 + 3 * PER_DESIGN + 200}", '"yes,no"': f"K2:K{1 + 3 * PER_DESIGN + 200}"}


def test_a_drop_task_has_no_in_tolerance_dropdown(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    plan = test_plans.create_test_plan(db, config, job_id, random_per_design=0)

    sheet = load_workbook(io.BytesIO(test_plans.plan_xlsx(db, job_id, plan.id)[1])).active

    assert [rule.formula1 for rule in sheet.data_validations.dataValidation] == ['"held,missed,skipped"']


def test_the_csv_leaves_the_prediction_out_unless_asked(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    plan = test_plans.create_test_plan(db, config, job_id, random_per_design=0)
    test_plans.predict_test_plan(db, plan.id, sim=FakeSim())

    name, blind = test_plans.plan_csv(db, job_id, plan.id)
    _, open_ = test_plans.plan_csv(db, job_id, plan.id, include_predicted=True)

    rows = list(csv.DictReader(io.StringIO(blind.decode("utf-8-sig"))))
    shown = list(csv.DictReader(io.StringIO(open_.decode("utf-8-sig"))))
    assert name.endswith("_EXP-0042_test-plan-1.csv") and blind.startswith(b"\xef\xbb\xbf")
    assert tuple(rows[0]) == test_plans.COLUMNS and len(rows) == 3 * 75
    assert {row["predicted"] for row in rows} == {""} and {row["predicted"] for row in shown} == {"yes", "no"}
    assert rows[0] | {"predicted": "yes"} == shown[0]


def test_unknown_plans_and_jobs(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    plan = test_plans.create_test_plan(db, config, job_id, random_per_design=0)
    other = add_job(db, profile_id, job_id="job2", number=43)

    with pytest.raises(test_plans.TestPlanNotFoundError):
        test_plans.get_test_plan(db, other, plan.id)
    with pytest.raises(test_plans.TestPlanNotFoundError):
        test_plans.plan_xlsx(db, job_id, plan.id + 1)
    with pytest.raises(test_plans.jobs.JobNotFoundError):
        test_plans.list_test_plans(db, "nope")
