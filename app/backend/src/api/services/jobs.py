"""Jobs (experiments) on the API side: plan, create, list, rename, duplicate, cancel and resume them, and launch the
detached worker that runs each one (python -m api.worker <job_id>). The API never calls the sim: the worker does
(services/optimizer.py for a generation job, services/evaluator.py for an evaluation job). Planning a generation job is
here; planning an evaluation job, and its results, are in services/evaluations.py.

Planning never raises for something the user can fix: every problem goes into the plan's blockers, each with the input
step whose screen fixes it, so the review screen can show them all at once and link back. Creating a blocked job is
refused with the same list.

A job snapshots what it runs with when it's created (the spec, the part as the gripper meets it in every resting pose it
covers, the plan, the grip force), so editing the part record or the cell profile later never changes a run or its
results.
"""

import datetime
import logging
import statistics
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from api.clients.database import DatabaseClient
from api.clients.sim import sim_badge
from api.config import AppConfig
from api.db.tables import JobRow, PartRow, TrialRow
from api.models import grasp
from api.models.cell_profile import DEFAULT_PROFILE, CellProfile, CellProfileVersion
from api.models.evaluation import EvaluationPlan, EvaluationSpec
from api.models.grasp import GraspChoice
from api.models.job import ACTIVE_STATUSES, RESUMABLE_STATUSES, Job, JobKind, JobStatus
from api.models.job_pose import JobPose, PoseChoice, pose_weights
from api.models.job_spec import JobSpec, PoseGrasp, SimBackend
from api.models.part import Part
from api.models.part_record import PartRecord
from api.models.resting_pose import RestingPose, is_same_pose
from api.models.results import CardScore, JobCard
from api.models.search_plan import Blocker, JobPlan, TimeEstimate, plan_job
from api.services import cell_profiles, compute, parts
from api.services.processes import pid_alive, spawn_detached

logger = logging.getLogger(__name__)

RECENT_TRIALS = 200  # search-grid trials the throughput estimate takes its median over
NUMBER_ATTEMPTS = 5  # tries at the next experiment number when another job takes it at the same moment
MAX_NAME = 200
STAND_IN_MASS_G = 1.0  # poses a part with no mass yet, so a blocked plan still shows its totals


class JobNotFoundError(LookupError):
    pass


class JobNotResumableError(RuntimeError):
    """The job isn't interrupted, cancelled or failed."""


class JobInputError(ValueError):
    """A request the job can't take: a blank name, or duplicating from a job that doesn't exist."""


class JobBlockedError(ValueError):
    """The spec can't run yet. blockers says why, each with the input step that fixes it."""

    def __init__(self, blockers: list[Blocker]):
        self.blockers = blockers
        super().__init__("; ".join(b.reason for b in blockers))

    @property
    def failed_step(self) -> int | None:
        return min((b.step for b in self.blockers), default=None)


@dataclass(frozen=True)
class SpecPlan:
    """A spec worked out: the plan (always there, blockers included), and what it was worked out from. part (the
    primary pose's), profile and record are None where they don't exist or couldn't be used; the plan then stands in
    for them (the default cell profile, a placeholder mass or part) so its totals still show, and its blockers say what
    to fix."""

    plan: JobPlan
    part: Part | None
    profile: CellProfileVersion | None
    record: PartRecord | None
    spec: JobSpec  # as given, with the cell profile's grasp accuracy filled in where it had no error model


def plan_spec(db: DatabaseClient, config: AppConfig, spec: JobSpec) -> SpecPlan:
    """The plan for a spec, as POST /api/jobs/plan shows it and POST /api/jobs stores it. Collects every user-fixable
    problem as a Blocker instead of raising: no part or no mass (step 1), no resting pose or one that doesn't exist (2),
    no cell profile (4), a grasp that the geometry check blocks in its pose (5), and families with no buildable design
    (6)."""
    blockers: list[Blocker] = []
    record = version = None
    try:
        record = parts.get_part(db, spec.part_id)
    except parts.PartNotFoundError:
        blockers.append(Blocker(step=1, reason=f"part {spec.part_id} doesn't exist: upload the part's CAD file"))
    try:
        version = cell_profiles.get_profile(db, spec.cell_profile_id)
    except cell_profiles.CellProfileNotFoundError:
        blockers.append(Blocker(step=4, reason=f"cell profile {spec.cell_profile_id} doesn't exist: choose a cell profile"))
    profile = version.profile if version is not None else DEFAULT_PROFILE
    spec = spec.with_error(profile.grasp_accuracy)

    poses: list[JobPose] = []
    if record is not None:
        if record.confirmed_mass_g is None:
            reason = "the part has no mass yet: choose its material (or enter a density) or enter a measured mass"
            blockers.append(Blocker(step=1, reason=reason))
        poses, found = _job_poses(db, spec, record, profile)
        blockers += found
    part = poses[0].part if poses else None
    planned = part or Part()  # a stand-in: the plan is blocked at step 1 or 2 and only its totals mean anything
    poses = poses or [JobPose(key="p0", grasp=_grasps(spec)[0], part=planned)]

    badge = sim_badge(config.sim.backend)
    clearance = record.clearance_mm if record is not None else None
    estimate = throughput(db, config, badge)
    plan = plan_job(planned, spec, profile, sim_backend=badge, estimate=estimate, clearance_mm=clearance, poses=poses)
    blockers += [Blocker(step=6, reason=reason) for reason in plan.blocked]
    blockers.sort(key=lambda b: b.step)
    force, warnings = grip_force(profile.grip_force_n, record)
    plan = plan.model_copy(
        update={"blockers": blockers, "blocked": [b.reason for b in blockers], "grip_force_n": force, "warnings": plan.warnings + warnings}
    )
    usable = record is not None and record.confirmed_mass_g is not None and all(pose.resting is not None for pose in poses)
    return SpecPlan(plan=plan, part=part if usable else None, profile=version, record=record, spec=spec)


def _grasps(spec: JobSpec) -> list[GraspChoice]:
    return [spec.grasp] if spec.grasp is not None else [pose.grasp for pose in spec.poses]


def _job_poses(db: DatabaseClient, spec: JobSpec, record: PartRecord, profile: CellProfile) -> tuple[list[JobPose], list[Blocker]]:
    """The resting poses the spec covers, primary (the likeliest) first, each with its weight, its grasp re-checked in
    that pose on this cell's gripper, and the part posed and turned to it; and what blocks them. A spec with one grasp
    (as every spec was before jobs covered poses) covers the part record's chosen pose. A part without a mass is posed
    with a stand-in, so a blocked plan still has its totals."""
    blockers: list[Blocker] = []
    if spec.grasp is not None:
        if record.pose is None:
            blockers.append(Blocker(step=2, reason="no resting pose chosen: choose how the part lies on the table"))
        chosen: list[tuple[PoseChoice | None, RestingPose | None, GraspChoice]] = [(None, record.pose, spec.grasp)]
    else:
        try:
            resting = parts.resolve_poses(record, [p.pose for p in spec.poses])
        except parts.PartInputError as e:
            return [], [Blocker(step=2, reason=f"resting pose: {e}")]
        chosen = [(p.pose, r, p.grasp) for p, r in zip(spec.poses, resting, strict=True)]
        chosen.sort(key=lambda c: (-(c[1].probability or 0.0), c[0] if isinstance(c[0], int) else 0))
    posed = record if record.confirmed_mass_g is not None else record.model_copy(update={"mass_g": STAND_IN_MASS_G})
    try:
        mesh = parts.load_mesh(record)
    except OSError as e:
        return [], [*blockers, Blocker(step=1, reason=f"the part can't be posed ({e}): upload its CAD file again")]
    weights = pose_weights([resting.probability if resting is not None else None for _, resting, _ in chosen])
    poses = []
    for i, ((choice, resting, g), weight) in enumerate(zip(chosen, weights, strict=True)):
        label = resting.label if resting is not None else None
        where = f" ({label})" if len(chosen) > 1 else ""
        if resting is not None:
            blockers += _grasp_blockers(db, record, profile, g, resting, where)
        try:
            part = grasp.posed_part(posed, g, profile.pad_friction, mesh, pose=resting)
        except ValueError as e:
            return [], [*blockers, Blocker(step=1, reason=f"the part can't be posed ({e}): upload its CAD file again")]
        probability = resting.probability if resting is not None else None
        poses.append(
            JobPose(key=f"p{i}", label=label, choice=choice, probability=probability, weight=weight, resting=resting, grasp=g, part=part)
        )
    return poses, blockers


def _grasp_blockers(
    db: DatabaseClient, record: PartRecord, profile: CellProfile, g: GraspChoice, resting: RestingPose, where: str
) -> list[Blocker]:
    """The grasp re-checked in its pose on this cell's gripper: what blocks it, at step 5."""
    try:
        candidate = parts.check_grasp(
            db,
            record.id,
            profile,
            angle_deg=g.angle_deg,
            picks=g.picks,
            grip_height_mm=g.grip_height_mm,
            pose=resting,
            centre_mm=g.centre_mm if g.span_mm is not None else None,
            span_mm=g.span_mm,
        )
    except parts.PartInputError as e:
        return [Blocker(step=5, reason=f"grasp{where}: {e}")]
    if candidate.verdict != "blocked":
        return []
    reasons = candidate.blocked_reasons or [f"the grasp at {g.angle_deg:g} deg doesn't fit this gripper"]
    return [Blocker(step=5, reason=f"grasp{where}: {reason}") for reason in reasons]


def grip_force(profile_force: float | None, record: PartRecord | None) -> tuple[float | None, list[str]]:
    """The per-jaw force sent with every batch: the lesser of the cell's and the part's limit where either is known."""
    part_force = record.max_grip_force_n if record is not None else None
    known = [f for f in (profile_force, part_force) if f is not None]
    warnings = []
    if record is not None and record.fragile and part_force is None:
        warnings.append("the part is marked fragile but has no max grip force: the sim grips it with the cell's full force")
    return (min(known) if known else None), warnings


def throughput(db: DatabaseClient, config: AppConfig, badge: SimBackend) -> TimeEstimate:
    """Grasps per second for time estimates: the median over recent search-grid trials on the same sim backend
    (measured), else SIM_GRASPS_PER_S (configured), else unknown. A trial's duration is its share of its round's sim
    time, so grasps / duration is the round's rate."""
    query = (
        select(TrialRow.n_grasps, TrialRow.duration)
        .join(JobRow, JobRow.id == TrialRow.job_id)
        .where(JobRow.sim_backend == badge, TrialRow.grid == "search", TrialRow.duration > 0)
        .order_by(TrialRow.created.desc())
        .limit(RECENT_TRIALS)
    )
    with db.session() as s:
        rates = [n / duration for n, duration in s.execute(query)]
    if rates:
        return TimeEstimate(seconds=None, grasps_per_s=statistics.median(rates), source="measured")
    if config.sim.grasps_per_s:
        return TimeEstimate(seconds=None, grasps_per_s=config.sim.grasps_per_s, source="configured")
    return TimeEstimate(seconds=None, grasps_per_s=None, source="unknown")


def plan_any(db: DatabaseClient, config: AppConfig, spec: JobSpec | EvaluationSpec) -> JobPlan | EvaluationPlan:
    """The plan for a spec of either kind, as POST /api/jobs/plan shows it."""
    if spec.kind == "evaluation":
        from api.services import evaluations  # here: the evaluations service builds on this one

        return evaluations.plan_evaluation(db, config, spec).plan
    return plan_spec(db, config, spec).plan


def create_job(
    db: DatabaseClient,
    config: AppConfig,
    spec: JobSpec | EvaluationSpec,
    *,
    duplicated_from: str | None = None,
    start: bool = True,
    batch_id: str | None = None,
) -> Job:
    """Plan the spec, store the job with everything it runs with, and start its worker (start=False leaves it queued for
    the caller to run in-process, as the demo data does). A JobSpec makes a generation job, an EvaluationSpec an
    evaluation job. Raises JobBlockedError while the plan has blockers, and compute.ComputeNotReadyError when the app
    manages the GPU and it isn't ready. The experiment number is the next free one, fixed for life."""
    if start:
        compute.claim(db, config)
    if spec.kind == "evaluation":
        from api.services import evaluations

        planned = evaluations.plan_evaluation(db, config, spec)
        plan = planned.plan
        part = plan.part
        n_total = plan.totals.simulated + min(plan.finalists + 1, len(plan.fingers)) * len(plan.poses)
        n_rounds = plan.totals.batches
    else:
        planned = plan_spec(db, config, spec)
        plan, part = planned.plan, planned.part
        n_total, n_rounds = plan.totals.search_designs + plan.totals.final_designs, plan.totals.rounds
    if planned.plan.blockers:
        raise JobBlockedError(planned.plan.blockers)
    if duplicated_from is not None and not _exists(db, duplicated_from):
        raise JobInputError(f"duplicated_from: there's no job {duplicated_from}")
    name = _clean_name(spec.name or "") or default_name(planned.record)
    if len(name) > MAX_NAME:
        raise JobInputError(f"names are at most {MAX_NAME} characters")
    job_id = uuid.uuid4().hex[:10]
    values = {
        "id": job_id,
        "name": name,
        "kind": spec.kind,
        "status": "queued",
        "part_id": spec.part_id,
        "cell_profile_id": planned.profile.id,
        "sim_backend": plan.sim_backend,
        "spec": planned.spec.model_copy(update={"name": name}),
        "part": part,
        "plan": plan,
        "n_total": n_total,
        "n_rounds": n_rounds,
        "duplicated_from": duplicated_from,
        "print_designs": [],
        "batch_id": batch_id,
    }
    for attempt in range(1, NUMBER_ATTEMPTS + 1):
        try:
            with db.session() as s:  # committed before the worker starts, so it finds the job
                s.add(JobRow(experiment_number=_max_experiment_number(s) + 1, **values))
            break
        except IntegrityError:
            if attempt == NUMBER_ATTEMPTS:
                raise
            logger.warning("Job %s: experiment number taken at the same moment; retrying", job_id)
    job = get_job(db, job_id)
    logger.info(
        "Job %s: created %s %s %r (%s, %d trials planned)", job_id, job.kind, job.experiment_id, name, plan.sim_backend, job.n_total
    )
    if start:
        spawn_worker(db, config, job_id)
    return job


def create_evaluations(
    db: DatabaseClient, config: AppConfig, spec: EvaluationSpec, part_ids: list[str], *, start: bool = True
) -> list[Job]:
    """One evaluation job per part (a new customer order, say), each like `spec` but for its own part, sharing a batch
    id. Every part's plan is checked first, so a blocked part creates none of them (JobBlockedError, its reasons prefixed
    with the part). Poses chosen in `spec` must exist for every part; left empty, each part covers its own likely ones."""
    if not part_ids:
        raise JobInputError("a batch needs at least one part")
    if len(set(part_ids)) != len(part_ids):
        raise JobInputError("each part can be chosen once")
    from api.services import evaluations

    specs = [spec.model_copy(update={"part_id": part_id, "name": None if len(part_ids) > 1 else spec.name}) for part_id in part_ids]
    blockers = []
    for each in specs:
        planned = evaluations.plan_evaluation(db, config, each)
        label = planned.record.name if planned.record is not None else each.part_id
        blockers += [b.model_copy(update={"reason": f"{label}: {b.reason}"}) for b in planned.plan.blockers]
    if blockers:
        raise JobBlockedError(blockers)
    batch_id = uuid.uuid4().hex[:10] if len(part_ids) > 1 else None
    return [create_job(db, config, each, start=start, batch_id=batch_id) for each in specs]


def default_name(record: PartRecord | None) -> str:
    """ "<CAD file stem>_<YYYY-MM-DD>", e.g. "vial-cap_2026-10-19"."""
    stem = Path(record.name).stem if record is not None else "experiment"
    return f"{stem}_{datetime.date.today().isoformat()}"


def _max_experiment_number(s) -> int:
    return s.scalar(select(func.max(JobRow.experiment_number))) or 0


def list_jobs(
    db: DatabaseClient,
    *,
    part_id: str | None = None,
    status: JobStatus | None = None,
    backend: SimBackend | None = None,
    kind: JobKind | None = None,
    batch_id: str | None = None,
) -> list[Job]:
    """Every job, newest first, filtered by part, status, sim badge, kind or batch."""
    query = select(JobRow).order_by(JobRow.created.desc(), JobRow.experiment_number.desc())
    if kind is not None:
        query = query.where(JobRow.kind == kind)
    if batch_id is not None:
        query = query.where(JobRow.batch_id == batch_id)
    if part_id is not None:
        query = query.where(JobRow.part_id == part_id)
    if status is not None:
        query = query.where(JobRow.status == status)
    if backend is not None:
        query = query.where(JobRow.sim_backend == backend)
    with db.session() as s:
        return [Job.model_validate(row) for row in s.scalars(query)]


def get_job(db: DatabaseClient, job_id: str) -> Job:
    with db.session() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        return Job.model_validate(row)


def update_job(db: DatabaseClient, job_id: str, **values) -> None:
    """Set columns of the job row, e.g. status or progress."""
    with db.session() as s:
        s.execute(update(JobRow).where(JobRow.id == job_id).values(**values))


def job_cards(
    db: DatabaseClient,
    *,
    part_id: str | None = None,
    status: JobStatus | None = None,
    backend: SimBackend | None = None,
    kind: JobKind | None = None,
    batch_id: str | None = None,
) -> list[JobCard]:
    """The job list: one card per job, newest first."""
    return _cards(db, list_jobs(db, part_id=part_id, status=status, backend=backend, kind=kind, batch_id=batch_id))


def job_card(db: DatabaseClient, job_id: str) -> JobCard:
    return _cards(db, [get_job(db, job_id)])[0]


def _cards(db: DatabaseClient, found: list[Job]) -> list[JobCard]:
    """Cards for these jobs: part names in one query, and for finished jobs D1 and STOCK from their final trials (an
    evaluation job: its best finger and its stock fingers)."""
    # Imported here: the results tracker's services read jobs through this module, so a top-level import could cycle.
    from api.services import evaluations, physical_trials

    done = [job.id for job in found if job.status == "done" and job.kind == "generation"]
    with db.session() as s:
        names = dict(s.execute(select(PartRow.id, PartRow.name).where(PartRow.id.in_({job.part_id for job in found}))).all())
        query = select(TrialRow.job_id, TrialRow.label, TrialRow.success_rate, TrialRow.capture_radius_mm).where(
            TrialRow.job_id.in_(done), TrialRow.grid == "final", TrialRow.label.in_(("D1", "STOCK"))
        )
        finals = {
            (job_id, label): CardScore(label=label, success=rate, capture_radius_mm=radius)
            for job_id, label, rate, radius in s.execute(query)
        }
    for job in found:
        if job.kind == "evaluation" and job.status == "done":
            best, stock = evaluations.card_scores(db, job)
            for label, score in (("D1", best), ("STOCK", stock)):
                if score is not None:
                    finals[(job.id, label)] = CardScore(label=score[0], success=score[1], capture_radius_mm=score[2])
    return [
        JobCard(
            id=job.id,
            experiment_id=job.experiment_id,
            name=job.name,
            kind=job.kind,
            batch_id=job.batch_id,
            part_id=job.part_id,
            part_name=names.get(job.part_id),
            task_kind=job.spec.task.kind,
            sim_backend=job.sim_backend,
            status=job.status,
            round=job.round,
            n_rounds=job.n_rounds,
            n_done=job.n_done,
            n_total=job.n_total,
            best_value=job.best_value,
            winner=finals.get((job.id, "D1")),
            stock=finals.get((job.id, "STOCK")),
            failure=job.failure if job.status == "failed" else None,
            failed_step=job.failed_step if job.status == "failed" else None,
            physical_badge=physical_trials.physical_badge(db, job.id),
            created=job.created,
            finished=job.finished,
            duplicated_from=job.duplicated_from,
        )
        for job in found
    ]


def rename_job(db: DatabaseClient, job_id: str, name: str) -> Job:
    """A new name. The experiment ID never changes, so printed fingers and logged trials still match."""
    name = _clean_name(name)
    if not name:
        raise JobInputError("an experiment needs a name")
    if len(name) > MAX_NAME:
        raise JobInputError(f"names are at most {MAX_NAME} characters")
    with db.session() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        row.name = name
    logger.info("Job %s: renamed %r", job_id, name)
    return get_job(db, job_id)


def duplicate_job(db: DatabaseClient, job_id: str) -> JobSpec | EvaluationSpec:
    """A copy of the job's spec named "<name> (copy)", for the wizard to edit. Nothing is stored or started. A spec with
    one grasp (from before jobs covered poses) comes back with that grasp on its pose in `poses`, when the pose can still
    be found among the part's; otherwise as it was. An evaluation job's copy tries every compatible finger again when
    it did (finger_ids None), so fingers added to the library since are evaluated too."""
    job = get_job(db, job_id)
    spec = job.spec.model_copy(update={"name": f"{job.name} (copy)"})
    if spec.kind == "evaluation" or spec.grasp is None:
        return spec
    try:
        record = parts.get_part(db, job.part_id)
        resting = job.plan.poses[0].resting if job.plan.poses else record.pose
        choice = _pose_choice(record, resting)
    except (parts.PartNotFoundError, OSError):
        return spec
    if choice is None:
        return spec
    return spec.model_copy(update={"grasp": None, "poses": [PoseGrasp(pose=choice, grasp=spec.grasp)]})


def _pose_choice(record: PartRecord, resting: RestingPose | None) -> PoseChoice | None:
    """Which of the part's resting poses this is, as a job spec's poses name it; None if it isn't one of them."""
    if resting is None:
        return None
    if resting.source == "as_authored":
        return "as_authored"
    listed = parts.resting_poses_of(record)
    return next((i for i, pose in enumerate(listed) if pose.source == "stable" and is_same_pose(pose, resting)), None)


def cancel_job(db: DatabaseClient, job_id: str) -> None:
    """Ask the worker to stop. It checks between rounds, then marks the job cancelled; the rounds done so far are kept."""
    get_job(db, job_id)
    update_job(db, job_id, cancel_requested=1)


def resume_job(db: DatabaseClient, config: AppConfig, job_id: str) -> None:
    """Restart an interrupted, cancelled or failed job. The worker continues after the last checkpointed round."""
    job = get_job(db, job_id)
    if job.status not in RESUMABLE_STATUSES:
        raise JobNotResumableError(f"job {job_id} is {job.status}: only {', '.join(RESUMABLE_STATUSES)} jobs can be resumed")
    compute.claim(db, config)
    update_job(db, job_id, cancel_requested=0)  # an earlier cancel is answered; a new one, sent while queued, will be seen
    spawn_worker(db, config, job_id)


def spawn_worker(db: DatabaseClient, config: AppConfig, job_id: str, *args: str) -> int:
    """Start a detached worker process, python -m api.worker <job_id> [args], so it never blocks, or dies with, the web
    server, and return its pid. With no args it runs the job (and marks it queued); args select another task for the
    job, e.g. predicting a test plan or recording a clip."""
    pid = spawn_detached([sys.executable, "-m", "api.worker", job_id, *args], config.worker_log)
    if not args:
        update_job(db, job_id, status="queued", pid=pid)
    logger.info("Job %s: worker started (pid %s)%s", job_id, pid, f" for {' '.join(args)}" if args else "")
    return pid


def mark_interrupted(db: DatabaseClient) -> None:
    """At API startup, mark jobs whose worker is gone as interrupted, so they can be resumed from their checkpoint."""
    with db.session() as s:
        for row in s.scalars(select(JobRow).where(JobRow.status.in_(ACTIVE_STATUSES))):
            if not pid_alive(row.pid):
                row.status = "interrupted"
                logger.warning("Job %s: its worker is gone; marked interrupted", row.id)


def _exists(db: DatabaseClient, job_id: str) -> bool:
    with db.session() as s:
        return s.get(JobRow, job_id) is not None


def _clean_name(name: str) -> str:
    """A name as it's stored: trimmed, with runs of whitespace as one space."""
    return " ".join(name.split())
