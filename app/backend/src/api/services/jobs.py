"""Jobs on the API side: create, read, cancel and resume them, and launch the detached worker that runs each one."""

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import select, update

from api.clients.database import DatabaseClient
from api.config import APP_DIR, AppConfig
from api.db.tables import JobRow, ResultRow, RunMetaRow, TrialRow
from api.models.design import Design
from api.models.finger import Finger, build_finger
from api.models.job import RESUMABLE_STATUSES, Job, JobConfig, JobDetail, JobResult, Trial
from api.models.part import Part
from api.services import physical_trials, reviews

logger = logging.getLogger(__name__)


class JobNotFoundError(LookupError):
    pass


class JobNotResumableError(RuntimeError):
    """The job doesn't exist or isn't interrupted, cancelled or failed."""


def create_job(
    db: DatabaseClient, config: AppConfig, *, task: str, part: Part, job_config: JobConfig, upload: tuple[str, bytes] | None = None
) -> str:
    """Store a new job, save the uploaded part file if any, and start its worker. Returns the job id."""
    job_id = uuid.uuid4().hex[:10]
    part_name, part_path = "manual", None
    if upload:
        filename, content = upload
        part_name = Path(filename).name
        config.uploads_dir.mkdir(parents=True, exist_ok=True)
        part_path = config.uploads_dir / f"{job_id}_{part_name}"
        part_path.write_bytes(content)
    with db.session() as s:  # committed before the worker starts, so it finds the job
        s.add(
            JobRow(
                id=job_id,
                status="queued",
                part_name=part_name,
                part_path=str(part_path) if part_path else None,
                part=part,
                task=task,
                config=job_config,
                n_total=job_config.budget,
            )
        )
    logger.info("Job %s: created (%s)", job_id, part_name)
    spawn_worker(db, config, job_id)
    return job_id


def list_jobs(db: DatabaseClient) -> list[Job]:
    with db.session() as s:
        return [Job.model_validate(row) for row in s.scalars(select(JobRow).order_by(JobRow.created.desc()))]


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


def get_job_detail(db: DatabaseClient, job_id: str) -> JobDetail:
    """The job plus everything it produced so far."""
    with db.session() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        trials = s.scalars(select(TrialRow).where(TrialRow.job_id == job_id).order_by(TrialRow.number))
        result, meta = s.get(ResultRow, job_id), s.get(RunMetaRow, job_id)
        return JobDetail(
            job=Job.model_validate(row),
            trials=[Trial.model_validate(r) for r in trials],
            result=JobResult.model_validate(result) if result else None,
            meta=meta.meta if meta else None,
            review=reviews.get_review(db, job_id),
            physical=physical_trials.list_trials(db, job_id),
        )


def cancel_job(db: DatabaseClient, job_id: str) -> None:
    """Ask the worker to stop. It checks between batches, then marks the job cancelled."""
    update_job(db, job_id, cancel_requested=1)


def resume_job(db: DatabaseClient, config: AppConfig, job_id: str) -> None:
    """Restart an interrupted, cancelled or failed job. The worker continues from the last checkpointed trial."""
    with db.session() as s:
        row = s.get(JobRow, job_id)
        if row is None or row.status not in RESUMABLE_STATUSES:
            raise JobNotResumableError(job_id)
    spawn_worker(db, config, job_id)


def result_finger(db: DatabaseClient, job_id: str) -> tuple[Part, Finger]:
    """The part and the winning finger's geometry, for the 3D preview."""
    with db.session() as s:
        job, result = s.get(JobRow, job_id), s.get(ResultRow, job_id)
        if job is None or result is None:
            raise JobNotFoundError(job_id)
        part, design = job.part, Design(kind=result.kind, params=result.params)
    return part, build_finger(part, design)


def result_file(db: DatabaseClient, job_id: str) -> Path:
    """The winning design's CAD file."""
    with db.session() as s:
        result = s.get(ResultRow, job_id)
        if result is None:
            raise JobNotFoundError(job_id)
        return Path(result.scad_path)


def spawn_worker(db: DatabaseClient, config: AppConfig, job_id: str) -> None:
    """Start the job as a detached process (api.worker), so it never blocks, or dies with, the web server."""
    if os.name == "nt":
        detach = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        detach = {"start_new_session": True}
    config.worker_log.parent.mkdir(parents=True, exist_ok=True)
    with open(config.worker_log, "a") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "api.worker", job_id], cwd=APP_DIR, stdout=log, stderr=subprocess.STDOUT, **detach
        )
    update_job(db, job_id, status="queued", pid=process.pid)
    logger.info("Job %s: worker started (pid %s)", job_id, process.pid)


def mark_interrupted(db: DatabaseClient) -> None:
    """At API startup, mark jobs whose worker is gone as interrupted, so they can be resumed from their checkpoint."""
    with db.session() as s:
        for row in s.scalars(select(JobRow).where(JobRow.status.in_(("queued", "running")))):
            if not _pid_alive(row.pid):
                row.status = "interrupted"
                logger.warning("Job %s: its worker is gone; marked interrupted", row.id)


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
            return str(pid) in out
        os.kill(pid, 0)
        return True
    except OSError:
        return False
