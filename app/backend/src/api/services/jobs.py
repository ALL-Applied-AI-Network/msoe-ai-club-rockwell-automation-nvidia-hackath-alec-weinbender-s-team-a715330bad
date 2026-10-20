"""Experiments on the API side: plan, create, list, rename, duplicate, cancel and resume them, and launch the detached
worker that runs each one (python -m api.worker <job_id>). The API never calls the sim: the worker does
(services/optimizer.py).

Planning never raises for something the user can fix: every problem goes into the plan's blockers, each with the input
step whose screen fixes it, so the review screen can show them all at once and link back. Creating a blocked job is
refused with the same list.

A job snapshots what it runs with when it's created (the spec, the part as the gripper meets it, the plan, the grip
force), so editing the part record or the cell profile later never changes a run or its results.
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
from api.models.job import ACTIVE_STATUSES, RESUMABLE_STATUSES, Job, JobStatus
from api.models.job_spec import JobSpec, SimBackend
from api.models.part import Part
from api.models.part_record import PartRecord
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
    """A spec worked out: the plan (always there, blockers included), and what it was worked out from. part, profile
    and record are None where they don't exist or couldn't be used; the plan then stands in for them (the default cell
    profile, a placeholder mass or part) so its totals still show, and its blockers say what to fix."""

    plan: JobPlan
    part: Part | None
    profile: CellProfileVersion | None
    record: PartRecord | None


def plan_spec(db: DatabaseClient, config: AppConfig, spec: JobSpec) -> SpecPlan:
    """The plan for a spec, as POST /api/jobs/plan shows it and POST /api/jobs stores it. Collects every user-fixable
    problem as a Blocker instead of raising: no part or no mass (step 1), no resting pose (2), no cell profile (4), a
    grasp that the geometry check blocks (5), and families with no buildable design (6)."""
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

    part = None
    if record is not None:
        blockers += _record_blockers(db, spec, record, profile)
        posed = record if record.confirmed_mass_g is not None else record.model_copy(update={"mass_g": STAND_IN_MASS_G})
        try:
            part = grasp.posed_part(posed, spec.grasp, profile.pad_friction, parts.load_mesh(record))
        except (OSError, ValueError) as e:
            blockers.append(Blocker(step=1, reason=f"the part can't be posed ({e}): upload its CAD file again"))
    planned = part or Part()  # a stand-in: the plan is blocked at step 1 and only its totals mean anything

    badge = sim_badge(config.sim.backend)
    clearance = record.clearance_mm if record is not None else None
    plan = plan_job(planned, spec, profile, sim_backend=badge, estimate=throughput(db, config, badge), clearance_mm=clearance)
    blockers += [Blocker(step=6, reason=reason) for reason in plan.blocked]
    blockers.sort(key=lambda b: b.step)
    force, warnings = _grip_force(profile.grip_force_n, record)
    plan = plan.model_copy(
        update={"blockers": blockers, "blocked": [b.reason for b in blockers], "grip_force_n": force, "warnings": plan.warnings + warnings}
    )
    usable = record is not None and record.confirmed_mass_g is not None and record.pose is not None
    return SpecPlan(plan=plan, part=part if usable else None, profile=version, record=record)


def _record_blockers(db: DatabaseClient, spec: JobSpec, record: PartRecord, profile: CellProfile) -> list[Blocker]:
    """What the part record still needs (mass, pose), and the grasp re-checked against it on this cell's gripper."""
    out = []
    if record.confirmed_mass_g is None:
        out.append(Blocker(step=1, reason="the part has no mass yet: choose its material (or enter a density) or enter a measured mass"))
    if record.pose is None:
        out.append(Blocker(step=2, reason="no resting pose chosen: choose how the part lies on the table"))
        return out
    g = spec.grasp
    try:
        candidate = parts.check_grasp(db, record.id, profile, angle_deg=g.angle_deg, picks=g.picks, grip_height_mm=g.grip_height_mm)
    except parts.PartInputError as e:
        return [*out, Blocker(step=5, reason=f"grasp: {e}")]
    except parts.PoseNotChosenError:
        return [*out, Blocker(step=2, reason="no resting pose chosen: choose how the part lies on the table")]
    if candidate.verdict == "blocked":
        reasons = candidate.blocked_reasons or [f"the grasp at {g.angle_deg:g} deg doesn't fit this gripper"]
        out += [Blocker(step=5, reason=f"grasp: {reason}") for reason in reasons]
    return out


def _grip_force(profile_force: float | None, record: PartRecord | None) -> tuple[float | None, list[str]]:
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


def create_job(db: DatabaseClient, config: AppConfig, spec: JobSpec, *, duplicated_from: str | None = None, start: bool = True) -> Job:
    """Plan the spec, store the job with everything it runs with, and start its worker (start=False leaves it queued for
    the caller to run in-process, as the demo data does). Raises JobBlockedError while the plan has blockers, and
    compute.ComputeNotReadyError when the app manages the GPU and it isn't ready. The experiment number is the next free
    one, fixed for life."""
    if start:
        compute.claim(db, config)
    planned = plan_spec(db, config, spec)
    if planned.plan.blockers:
        raise JobBlockedError(planned.plan.blockers)
    if duplicated_from is not None and not _exists(db, duplicated_from):
        raise JobInputError(f"duplicated_from: there's no job {duplicated_from}")
    name = _clean_name(spec.name or "") or default_name(planned.record)
    if len(name) > MAX_NAME:
        raise JobInputError(f"names are at most {MAX_NAME} characters")
    plan = planned.plan
    job_id = uuid.uuid4().hex[:10]
    values = {
        "id": job_id,
        "name": name,
        "status": "queued",
        "part_id": spec.part_id,
        "cell_profile_id": planned.profile.id,
        "sim_backend": plan.sim_backend,
        "spec": spec.model_copy(update={"name": name}),
        "part": planned.part,
        "plan": plan,
        "n_total": plan.totals.search_designs + plan.totals.final_designs,
        "n_rounds": plan.totals.rounds,
        "duplicated_from": duplicated_from,
        "print_designs": [],
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
    logger.info("Job %s: created %s %r (%s, %d designs planned)", job_id, job.experiment_id, name, plan.sim_backend, job.n_total)
    if start:
        spawn_worker(db, config, job_id)
    return job


def default_name(record: PartRecord | None) -> str:
    """ "<CAD file stem>_<YYYY-MM-DD>", e.g. "vial-cap_2026-10-19"."""
    stem = Path(record.name).stem if record is not None else "experiment"
    return f"{stem}_{datetime.date.today().isoformat()}"


def _max_experiment_number(s) -> int:
    return s.scalar(select(func.max(JobRow.experiment_number))) or 0


def list_jobs(
    db: DatabaseClient, *, part_id: str | None = None, status: JobStatus | None = None, backend: SimBackend | None = None
) -> list[Job]:
    """Every job, newest first, filtered by part, status or sim badge."""
    query = select(JobRow).order_by(JobRow.created.desc(), JobRow.experiment_number.desc())
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
    db: DatabaseClient, *, part_id: str | None = None, status: JobStatus | None = None, backend: SimBackend | None = None
) -> list[JobCard]:
    """The job list: one card per job, newest first."""
    return _cards(db, list_jobs(db, part_id=part_id, status=status, backend=backend))


def job_card(db: DatabaseClient, job_id: str) -> JobCard:
    return _cards(db, [get_job(db, job_id)])[0]


def _cards(db: DatabaseClient, found: list[Job]) -> list[JobCard]:
    """Cards for these jobs: part names in one query, and for finished jobs D1 and STOCK from their final trials."""
    # Imported here: the results tracker's services read jobs through this module, so a top-level import could cycle.
    from api.services import physical_trials

    done = [job.id for job in found if job.status == "done"]
    with db.session() as s:
        names = dict(s.execute(select(PartRow.id, PartRow.name).where(PartRow.id.in_({job.part_id for job in found}))).all())
        query = select(TrialRow.job_id, TrialRow.label, TrialRow.success_rate, TrialRow.capture_radius_mm).where(
            TrialRow.job_id.in_(done), TrialRow.grid == "final", TrialRow.label.in_(("D1", "STOCK"))
        )
        finals = {
            (job_id, label): CardScore(label=label, success=rate, capture_radius_mm=radius)
            for job_id, label, rate, radius in s.execute(query)
        }
    return [
        JobCard(
            id=job.id,
            experiment_id=job.experiment_id,
            name=job.name,
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


def duplicate_job(db: DatabaseClient, job_id: str) -> JobSpec:
    """A copy of the job's spec named "<name> (copy)", for the wizard to edit. Nothing is stored or started."""
    job = get_job(db, job_id)
    return job.spec.model_copy(update={"name": f"{job.name} (copy)"})


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
