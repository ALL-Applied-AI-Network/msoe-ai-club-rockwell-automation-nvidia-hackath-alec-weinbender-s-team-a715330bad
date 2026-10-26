"""Runs one evaluation job in the worker: every planned finger at every grasp of every pose on the sim, then the final
test, then the ranking's predictions written to the qualifications (how it scores: api/models/evaluation.py).

- Search: one sim request per (pose, grasp), carrying every finger that can grip there, on the search grid. Each request
  is checkpointed with the job's progress in one transaction, so a resumed job skips the requests it finished.
- Final: the top EVAL_FINALISTS fingers and the stock fingers, each at its best grasp per pose, on the dense grid, one
  request per (pose, grasp) they use. The final trials, the qualifications' predictions and the job's "done" are written
  together, so finishing is all or nothing and can simply be run again.

The worker's entry point is services/optimizer.py: run_job, which hands evaluation jobs to run_evaluation().
"""

import logging
import os
import time
import traceback
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update

from api.clients.database import DatabaseClient
from api.clients.sim import SimClient, SimError, SimSettings
from api.db.tables import EvaluationTrialRow, JobRow
from api.models.cell_profile import Gripper
from api.models.evaluation import EVAL_FINALISTS, EvaluationGrasp, EvaluationPlan, EvaluationPosePlan, EvaluationTrial
from api.models.finger import Finger
from api.models.finger_record import FingerRecord
from api.models.job import Job
from api.models.offset_grid import OffsetGrid
from api.models.qualification import Prediction
from api.services import cell_profiles, evaluations, fingers, parts, qualifications
from api.services.jobs import JobNotFoundError, get_job, update_job

logger = logging.getLogger(__name__)

TRACEBACK_CHARS = 4000


class EvaluationRunError(RuntimeError):
    """A failure the run can explain in one line, with the evaluation step that fixes it when there is one."""

    def __init__(self, line: str, step: int | None = None):
        super().__init__(line)
        self.line, self.step = line, step


@dataclass(frozen=True)
class _Run:
    job: Job
    gripper: Gripper
    records: list[FingerRecord]
    grips: dict[tuple[str, str, str], tuple[Finger | None, list[str]]]
    settings: SimSettings


def run_evaluation(db: DatabaseClient, job_id: str, *, sim: SimClient) -> None:
    """Run or resume an evaluation job to completion. A failure is stored on the job, not raised; a job that's already
    done is left alone."""
    started = time.time()
    try:
        job = get_job(db, job_id)
    except JobNotFoundError:
        logger.error("Job %s: not found", job_id)
        return
    if job.status == "done":
        logger.info("Job %s: already done", job_id)
        return
    update_job(db, job_id, status="running", pid=os.getpid(), error=None, failure=None, failed_step=None)
    logger.info("Job %s (%s): evaluating %d fingers on the %s sim", job_id, job.experiment_id, len(job.plan.fingers), sim.backend)
    try:
        if sim.badge != job.sim_backend:
            raise EvaluationRunError(
                f"this evaluation runs on the {job.sim_backend} sim, but this worker has the {sim.badge} one: set SIM_BACKEND "
                "back to resume it, or duplicate it to run on this sim"
            )
        run = _load(db, job)
        if not _search(db, run, sim) or _cancelled(db, job_id):
            return
        _finalize(db, run, sim)
        logger.info("Job %s: done in %.0f s", job_id, time.time() - started)
    except Exception as e:
        logger.exception("Job %s: failed", job_id)
        line, step = _failure(e)
        update_job(db, job_id, status="failed", error=traceback.format_exc()[-TRACEBACK_CHARS:], failure=line, failed_step=step)


def _load(db: DatabaseClient, job: Job) -> _Run:
    try:
        profile = cell_profiles.get_profile(db, job.cell_profile_id)
    except cell_profiles.CellProfileNotFoundError:
        raise EvaluationRunError(f"cell profile {job.cell_profile_id} no longer exists", step=4) from None
    records = []
    for planned in job.plan.fingers:
        try:
            records.append(fingers.get_finger(db, planned.finger_id))
        except fingers.FingerNotFoundError:
            logger.warning("Job %s: finger %s is no longer in the library; skipped", job.id, planned.code)
    try:
        clearance = parts.get_part(db, job.part_id).clearance_mm
    except parts.PartNotFoundError:
        clearance = None
    gripper = profile.profile.gripper
    return _Run(
        job=job,
        gripper=gripper,
        records=records,
        grips=evaluations.grips(records, job.plan.poses, gripper, clearance),
        settings=SimSettings(grip_force_n=job.plan.grip_force_n, transport=job.spec.task.transport),
    )


def _search(db: DatabaseClient, run: _Run, sim: SimClient) -> bool:
    """Every (pose, grasp) not checkpointed yet. False if the job was cancelled."""
    job = run.job
    done = {(t.pose_key, t.grasp_key) for t in evaluations.load_trials(db, job.id, "search")}
    for pose in job.plan.poses:
        for g in pose.grasps:
            if (pose.key, g.key) in done:
                continue
            if _cancelled(db, job.id):
                return False
            entries = [(r.id, run.grips[(r.id, pose.key, g.key)][0]) for r in run.records if not run.grips[(r.id, pose.key, g.key)][1]]
            rows = _simulate(run, sim, pose, g, entries, job.plan.grid, "search")
            _store(db, run, rows)
    return True


def _simulate(
    run: _Run,
    sim: SimClient,
    pose: EvaluationPosePlan,
    g: EvaluationGrasp,
    entries: list[tuple[str, Finger | None]],
    grid: OffsetGrid,
    stage: str,
) -> list[EvaluationTrialRow]:
    """One sim request: these fingers at this grasp, on this grid; a trial row per finger (numbered when stored)."""
    if not entries:
        return []
    started = time.perf_counter()
    results = sim.run_batch(g.part, [finger for _, finger in entries], grid.points(), run.settings)
    if len(results) != len(entries):
        raise SimError(f"the sim answered for {len(results)} fingers out of {len(entries)}")
    share = (time.perf_counter() - started) / len(entries)
    spec = run.job.spec
    rows = []
    for (finger_id, finger), outcomes in zip(entries, results, strict=True):
        success = spec.task.success(outcomes)
        rows.append(
            EvaluationTrialRow(
                job_id=run.job.id,
                number=0,
                stage=stage,
                finger_id=finger_id,
                pose_key=pose.key,
                grasp_key=g.key,
                success_rate=grid.expected_success(success, spec.error),
                capture_radius_mm=grid.capture_radius(success),
                n_grasps=grid.size,
                held=outcomes.held,
                in_hand=[None if p is None else list(p) for p in outcomes.in_hand],
                held_after_transport=outcomes.held_after_transport,
                tip_height_mm=None if finger is None else finger.tip_height_mm,
                jaw_close_mm=None if finger is None else finger.jaw_close_mm,
                duration=share,
            )
        )
    return rows


def _store(db: DatabaseClient, run: _Run, rows: list[EvaluationTrialRow]) -> None:
    """A search request's trials and the job's progress, in one transaction."""
    job_id = run.job.id
    with db.session() as s:
        first = (s.scalar(select(func.max(EvaluationTrialRow.number)).where(EvaluationTrialRow.job_id == job_id)) or 0) + 1
        for i, row in enumerate(rows):
            row.number = first + i
        s.add_all(rows)
        s.flush()
        n_done = s.scalar(select(func.count()).select_from(EvaluationTrialRow).where(EvaluationTrialRow.job_id == job_id))
        s.execute(update(JobRow).where(JobRow.id == job_id).values(n_done=n_done, round=JobRow.round + 1))
    logger.info("Job %s: %d fingers simulated", job_id, len(rows))


def _finalize(db: DatabaseClient, run: _Run, sim: SimClient) -> None:
    """The final test, then the predictions and "done", together."""
    job, plan = run.job, run.job.plan
    update_job(db, job.id, status="finalizing")
    searched = evaluations.load_trials(db, job.id, "search")
    scores = evaluations.score_fingers(plan, searched, job.spec.error, job.spec.task)
    sources = {r.id: r.source for r in run.records}
    tried = [s for s in scores if s.best and s.finger_id in sources]
    chosen = [s for s in tried if sources[s.finger_id] != "stock"][:EVAL_FINALISTS] + [s for s in tried if sources[s.finger_id] == "stock"]
    groups: dict[tuple[str, str], list[str]] = {}
    for score in chosen:
        for pose_key, (trial, _, _) in score.best.items():
            groups.setdefault((pose_key, trial.grasp_key), []).append(score.finger_id)
    rows = []
    for (pose_key, grasp_key), finger_ids in groups.items():
        pose, g = plan.pose(pose_key), plan.grasp(pose_key, grasp_key)
        entries = [(fid, run.grips[(fid, pose_key, grasp_key)][0]) for fid in finger_ids]
        rows += _simulate(run, sim, pose, g, entries, plan.final_grid, "final")
    final = [EvaluationTrial.model_validate({**_fields(row), "number": 0}) for row in rows]
    totals = evaluations.score_fingers(plan, searched + final, job.spec.error, job.spec.task)
    predictions = {score.finger_id: _prediction(job, plan, score) for score in totals if score.finger_id in sources}
    best = totals[0] if totals else None
    with db.session() as s:
        s.execute(delete(EvaluationTrialRow).where(EvaluationTrialRow.job_id == job.id, EvaluationTrialRow.stage == "final"))
        first = (s.scalar(select(func.max(EvaluationTrialRow.number)).where(EvaluationTrialRow.job_id == job.id)) or 0) + 1
        for i, row in enumerate(rows):
            row.number = first + i
        s.add_all(rows)
        qualifications.record_predictions(s, job.part_id, predictions)
        s.flush()
        n_done = s.scalar(select(func.count()).select_from(EvaluationTrialRow).where(EvaluationTrialRow.job_id == job.id))
        values = {"n_done": n_done, "round": JobRow.round + 1, "status": "done", "finished": time.time()}
        values["best_value"] = best.success if best is not None else None
        s.execute(update(JobRow).where(JobRow.id == job.id).values(**values))
    logger.info("Job %s: best finger %s %.3f", job.id, best.finger_id if best else None, best.success if best else 0.0)


def _fields(row: EvaluationTrialRow) -> dict:
    return {
        column.name: getattr(row, column.name)
        for column in EvaluationTrialRow.__table__.columns
        if column.name in EvaluationTrial.model_fields
    }


def _prediction(job: Job, plan: EvaluationPlan, score: evaluations.FingerScore) -> Prediction:
    grasps = [plan.grasp(pose.key, score.best[pose.key][0].grasp_key).grasp for pose in plan.poses if pose.key in score.best]
    return Prediction(
        job_id=job.id,
        experiment_id=job.experiment_id,
        success=score.success,
        stage=score.stage,
        n_grasps=score.n_grasps,
        error=job.spec.error,
        task=job.spec.task,
        grasps=grasps,
        sim_backend=job.sim_backend,
        created=time.time(),
    )


def _cancelled(db: DatabaseClient, job_id: str) -> bool:
    """Whether a cancel was asked for; if so, marks the job cancelled (the requests done so far stay, for a resume)."""
    with db.session() as s:
        if not s.scalar(select(JobRow.cancel_requested).where(JobRow.id == job_id)):
            return False
    update_job(db, job_id, status="cancelled")
    logger.info("Job %s: cancelled", job_id)
    return True


def _failure(error: Exception) -> tuple[str, int | None]:
    if isinstance(error, EvaluationRunError):
        return error.line, error.step
    if isinstance(error, SimError):
        return f"sim: {error}", None
    text = next((line.strip() for line in str(error).splitlines() if line.strip()), "")
    line = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return line[:300], None
