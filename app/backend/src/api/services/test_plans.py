"""Physical test plans (results tracker): the offsets to command on the real robot for each printed design, the sim's
prediction for every planned trial, and the plan as a spreadsheet to fill in at the robot.

A plan covers the print selection plus the IMP and STOCK baselines (services/printed_fingers.py). Per design it has the
point-wise offsets of api/models/test_plan.py, repeated, then offsets drawn from the job's error model with a seeded
numpy Generator: the seed is stored, so the same seed, designs and counts give the same plan. Trial IDs continue across
the job's plans and its extra trials (T0001, ...), so a trial ID alone names one attempt.

predict_test_plan() runs in the detached worker (python -m api.worker <job_id> predict <plan_id>), since only workers
call the sim. It never raises: a failure is stored on the plan (prediction_status "failed", prediction_error).

The spreadsheet's columns are COLUMNS. The app fills the first nine; the operator fills outcome (held, missed, skipped),
in_tolerance (yes / no, place and insert only), notes, video_link, operator and timestamp. predicted (the sim's task
success, yes / no) is hidden in the XLSX and left blank in the CSV unless asked for, so it can't bias whoever tests.
Outcomes already logged are filled in on download, and the plan's extra trials are listed under the planned ones, so a
downloaded sheet always uploads back unchanged. Uploading is the physical trials service's job.
"""

import logging
import secrets

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.clients.database import DatabaseClient
from api.clients.sim import SimClient, SimSettings
from api.config import AppConfig
from api.db.tables import PhysicalTrialRow, TestPlanRow
from api.models.finger import build_finger
from api.models.job import Job
from api.models.physical_trial import PhysicalTrial
from api.models.results import slug
from api.models.test_plan import (
    POINTWISE_REPEATS,
    RANDOM_PER_DESIGN,
    PlannedTrial,
    TestPlan,
    pointwise_offsets,
    random_offsets,
    trial_id,
    trial_number,
)
from api.services import cell_profiles, compute, jobs, printed_fingers, spreadsheets

logger = logging.getLogger(__name__)

COLUMNS = (
    "trial_id",
    "experiment_id",
    "design_id",
    "finger_id",
    "offset_x_mm",
    "offset_y_mm",
    "yaw_deg",
    "repeat",
    "predicted",
    "outcome",
    "in_tolerance",
    "notes",
    "video_link",
    "operator",
    "timestamp",
)
SHEET_TITLE = "test plan"


class TestPlanNotFoundError(LookupError):
    __test__ = False  # not a pytest class


class TestPlanError(ValueError):
    """A plan that can't be made as asked: no repeats, or nothing to test."""

    __test__ = False


def create_test_plan(
    db: DatabaseClient,
    config: AppConfig,
    job_id: str,
    *,
    pointwise_repeats: int = POINTWISE_REPEATS,
    random_per_design: int = RANDOM_PER_DESIGN,
    seed: int | None = None,
    start: bool = True,
) -> TestPlan:
    """Plan the physical test of a finished job's chosen designs and baselines, store it, and start the worker that
    predicts it (start=False leaves that to the caller). seed None picks one (stored with the plan)."""
    if pointwise_repeats < 1 or random_per_design < 0:
        raise TestPlanError("a plan needs at least one repeat of the point-wise offsets, and zero or more random ones")
    job = printed_fingers.done_job(db, job_id)
    designs = printed_fingers.tested_designs(job, list(printed_fingers.final_designs(db, job_id)))
    if not designs:
        raise TestPlanError(f"{job.experiment_id}'s final test has no labelled designs to test")
    seed = secrets.randbelow(2**31) if seed is None else seed
    finger_ids = printed_fingers.trial_finger_ids(db, job)
    with db.session() as s:
        first = next_trial_number(s, job_id)
        rows = _rows(job, designs, first, pointwise_repeats, random_per_design, np.random.default_rng(seed), finger_ids)
        row = TestPlanRow(job_id=job_id, seed=seed, designs=designs, rows=rows, prediction_status="pending")
        s.add(row)
        s.flush()
        plan = TestPlan.model_validate(row)
    logger.info("Job %s: test plan %s, %d trials of %s (seed %d)", job_id, plan.id, len(rows), ", ".join(designs), seed)
    return _start_prediction(db, config, plan) if start else plan


def predict_again(db: DatabaseClient, config: AppConfig, job_id: str, plan_id: int) -> TestPlan:
    """Start the prediction worker again, e.g. after a failure. The plan's offsets don't change."""
    get_test_plan(db, job_id, plan_id)
    with db.session() as s:
        row = s.get(TestPlanRow, plan_id)
        row.prediction_status, row.prediction_error = "pending", None
        plan = TestPlan.model_validate(row)
    return _start_prediction(db, config, plan)


def list_test_plans(db: DatabaseClient, job_id: str) -> list[TestPlan]:
    """The job's plans, oldest first."""
    printed_fingers.load_job(db, job_id)
    with db.session() as s:
        return [
            TestPlan.model_validate(row)
            for row in s.scalars(select(TestPlanRow).where(TestPlanRow.job_id == job_id).order_by(TestPlanRow.id))
        ]


def get_test_plan(db: DatabaseClient, job_id: str, plan_id: int) -> TestPlan:
    printed_fingers.load_job(db, job_id)
    with db.session() as s:
        row = s.get(TestPlanRow, plan_id)
        if row is None or row.job_id != job_id:
            raise TestPlanNotFoundError(plan_id)
        return TestPlan.model_validate(row)


def next_trial_number(s: Session, job_id: str) -> int:
    """The number after every trial ID the job has used, in its plans and its logged (extra) trials. Takes an open
    session, so the IDs are read and used in one unit of work."""
    ids = [planned.trial_id for rows in s.scalars(select(TestPlanRow.rows).where(TestPlanRow.job_id == job_id)) for planned in rows]
    ids += list(s.scalars(select(PhysicalTrialRow.trial_id).where(PhysicalTrialRow.job_id == job_id)))
    return max((n for n in map(trial_number, ids) if n is not None), default=0) + 1


def predict_test_plan(db: DatabaseClient, plan_id: int, *, sim: SimClient) -> None:
    """Simulate every planned trial of the plan and store each row's predicted outcome. Failures are stored on the plan
    (prediction_status "failed", prediction_error), not raised.

    Each design is rebuilt from its final-test trial (STOCK is the sim's own stock fingers) for the job's part and cell
    profile, and simulated once at each unique offset of its rows, with the job's grip force and transport. predicted is
    the task's success there; predicted_in_tolerance is the task's tolerance check (place and insert only). plan_id may
    come as text, straight from the worker's command line."""
    try:
        plan_id = int(plan_id)
        with db.session() as s:
            row = s.get(TestPlanRow, plan_id)
            if row is None:
                logger.error("Test plan %s: not found; nothing to predict", plan_id)
                return
            row.prediction_status, row.prediction_error = "running", None
            plan = TestPlan.model_validate(row)
        job = printed_fingers.load_job(db, plan.job_id)
        if sim.badge != job.sim_backend:
            logger.warning("Test plan %s: predicted on the %s sim, but job %s ran on %s", plan_id, sim.badge, job.id, job.sim_backend)
        gripper = cell_profiles.get_profile(db, job.cell_profile_id).profile.gripper
        designs = printed_fingers.final_designs(db, job.id)
        task = job.spec.task
        settings = SimSettings(grip_force_n=getattr(job.plan, "grip_force_n", None), transport=task.transport)
        predictions: dict[tuple[str, tuple[float, float, float]], tuple[bool, bool | None]] = {}
        for label in plan.designs:
            if label not in designs:
                raise ValueError(f"design {label} isn't in the job's final test")
            design = designs[label]
            finger = None if design is None else build_finger(job.part, design, gripper)
            offsets = list(dict.fromkeys(planned.offset for planned in plan.rows if planned.design_label == label))
            if not offsets:
                continue
            (outcomes,) = sim.run_batch(job.part, [finger], [{"dx": x, "dy": y, "yaw_deg": yaw} for x, y, yaw in offsets], settings)
            success = task.success(outcomes)
            for i, offset in enumerate(offsets):
                in_tolerance = None if task.kind == "drop" else task.within_tolerance(outcomes.in_hand[i])
                predictions[label, offset] = (success[i], in_tolerance)
        with db.session() as s:
            row = s.get(TestPlanRow, plan_id)
            row.rows = [_predicted(planned, predictions.get((planned.design_label, planned.offset))) for planned in row.rows]
            row.prediction_status = "done"
        logger.info("Test plan %s: predicted %d offsets on the %s sim", plan_id, len(predictions), sim.badge)
    except Exception as e:
        logger.exception("Test plan %s: prediction failed", plan_id)
        try:
            with db.session() as s:
                row = s.get(TestPlanRow, plan_id)
                if row is not None:
                    row.prediction_status, row.prediction_error = "failed", f"{type(e).__name__}: {e}"
        except Exception:
            logger.exception("Test plan %s: couldn't store the failure", plan_id)


def plan_xlsx(db: DatabaseClient, job_id: str, plan_id: int) -> tuple[str, bytes]:
    """(file name, the XLSX): dropdowns on outcome and (place / insert) in_tolerance, predicted hidden."""
    job, plan, rows = _sheet(db, job_id, plan_id, include_predicted=True)
    dropdowns = {"outcome": ("held", "missed", "skipped")}
    if job.spec.task.kind in ("place", "insert"):
        dropdowns["in_tolerance"] = ("yes", "no")
    content = spreadsheets.write_xlsx(COLUMNS, rows, title=SHEET_TITLE, dropdowns=dropdowns, hidden=("predicted",))
    return f"{export_stem(job)}_test-plan-{plan.id}.xlsx", content


def plan_csv(db: DatabaseClient, job_id: str, plan_id: int, *, include_predicted: bool = False) -> tuple[str, bytes]:
    """(file name, the CSV): the same columns, predicted blank unless include_predicted."""
    job, plan, rows = _sheet(db, job_id, plan_id, include_predicted=include_predicted)
    return f"{export_stem(job)}_test-plan-{plan.id}.csv", spreadsheets.write_csv(COLUMNS, rows)


def export_stem(job: Job) -> str:
    """What exported file names start with (D14): <slug(name)>_<EXP-id>, with the results page's slug, so every file of
    one experiment sorts together."""
    return f"{slug(job.name)}_{job.experiment_id}"


def yes_no(value: bool | None) -> str | None:
    return None if value is None else "yes" if value else "no"


def _rows(
    job: Job,
    designs: list[str],
    first: int,
    pointwise_repeats: int,
    random_per_design: int,
    rng: np.random.Generator,
    finger_ids: dict[str, str],
) -> list[PlannedTrial]:
    """Per design: every point-wise offset once per repeat (repeat by repeat, so one offset isn't tried three times in a
    row), then the random ones, drawn design by design from one generator."""
    rows, number = [], first
    yaw = not job.part.round_from_above
    for label in designs:
        offsets = [(x, y, 0.0, repeat, "pointwise") for repeat in range(1, pointwise_repeats + 1) for x, y in pointwise_offsets()]
        offsets += [(x, y, a, 1, "random") for x, y, a in random_offsets(job.spec.error, random_per_design, rng, yaw=yaw)]
        for x, y, a, repeat, kind in offsets:
            rows.append(
                PlannedTrial(
                    trial_id=trial_id(number),
                    design_label=label,
                    finger_id=finger_ids.get(label),
                    kind=kind,
                    offset_x_mm=x,
                    offset_y_mm=y,
                    yaw_deg=a,
                    repeat=repeat,
                )
            )
            number += 1
    return rows


def _start_prediction(db: DatabaseClient, config: AppConfig, plan: TestPlan) -> TestPlan:
    """Start the prediction worker. When the app manages the GPU and it isn't ready, the plan is kept and its prediction
    marked failed with the reason, for predict-again once the GPU is up."""
    try:
        compute.claim(db, config)
        jobs.spawn_worker(db, config, plan.job_id, "predict", str(plan.id))
    except compute.ComputeNotReadyError as e:
        error = str(e)
    except OSError as e:
        logger.exception("Test plan %s: couldn't start the prediction worker", plan.id)
        error = f"couldn't start the prediction worker: {e}"
    else:
        return plan
    with db.session() as s:
        row = s.get(TestPlanRow, plan.id)
        row.prediction_status, row.prediction_error = "failed", error
    return plan.model_copy(update={"prediction_status": "failed", "prediction_error": error})


def _predicted(planned: PlannedTrial, prediction: tuple[bool, bool | None] | None) -> PlannedTrial:
    if prediction is None:
        return planned
    return planned.model_copy(update={"predicted": prediction[0], "predicted_in_tolerance": prediction[1]})


def _sheet(db: DatabaseClient, job_id: str, plan_id: int, *, include_predicted: bool) -> tuple[Job, TestPlan, list[dict]]:
    """The plan's spreadsheet rows: every planned trial with whatever is logged for it, then the plan's extra trials."""
    plan = get_test_plan(db, job_id, plan_id)
    job = printed_fingers.load_job(db, job_id)
    finger_ids = printed_fingers.trial_finger_ids(db, job)
    query = select(PhysicalTrialRow).where(PhysicalTrialRow.job_id == job_id, PhysicalTrialRow.plan_id == plan_id)
    with db.session() as s:
        logged = {row.trial_id: PhysicalTrial.model_validate(row) for row in s.scalars(query)}
    rows = []
    for planned in plan.rows:
        trial = logged.get(planned.trial_id)
        finger = (trial.finger_id if trial else None) or planned.finger_id or finger_ids.get(planned.design_label)
        rows.append(_sheet_row(job, planned, trial, finger, planned.predicted if include_predicted else None))
    extras = sorted((t for t in logged.values() if t.kind == "extra"), key=lambda t: trial_number(t.trial_id) or 0)
    rows += [_sheet_row(job, trial, trial, trial.finger_id, None) for trial in extras]
    return job, plan, rows


def _sheet_row(
    job: Job, where: PlannedTrial | PhysicalTrial, trial: PhysicalTrial | None, finger: str | None, predicted: bool | None
) -> dict:
    row = {
        "trial_id": where.trial_id,
        "experiment_id": job.experiment_id,
        "design_id": where.design_label,
        "finger_id": finger,
        "offset_x_mm": where.offset_x_mm,
        "offset_y_mm": where.offset_y_mm,
        "yaw_deg": where.yaw_deg,
        "repeat": where.repeat,
        "predicted": yes_no(predicted),
    }
    if trial is not None:
        row |= {
            "outcome": trial.outcome,
            "in_tolerance": yes_no(trial.in_tolerance),
            "notes": trial.notes or None,
            "video_link": trial.video_link,
            "operator": trial.operator,
            "timestamp": trial.timestamp,
        }
    return row
