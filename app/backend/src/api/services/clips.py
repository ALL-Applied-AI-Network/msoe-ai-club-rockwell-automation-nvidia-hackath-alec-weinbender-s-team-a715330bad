"""Isaac Sim clips: one grasp of a finished experiment's final design, filmed at one grid point (api/models/clip.py).

request_clip stores the request and starts a worker (python -m api.worker <job_id> clip <clip_id>), like a test plan's
prediction. It needs an experiment run on the Isaac sim (the mock has nothing to film) and, when the app manages the GPU,
a ready session (compute.claim). Asking again for a design and offset that already has a clip returns that clip, unless
it failed.

The worker (record_clip) asks the sim server to film the grasp: the same finger, part, offset, grip force and transport
the job simulated, with the cameras on (SimClient.record). It saves one mp4 per view as <outputs>/<job>/clips/<id>_<view>.mp4
and compares the recording's outcome with the job's stored one at that offset. Near a design's capture edge the two can
differ, since a grasp there isn't repeatable (CONTEXT.md, risk 5).

A job covering several resting poses is filmed in its primary pose (job.part, the plan's first pose) only, and compared
with that pose's stored outcomes; filming the other poses is deferred.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from api.clients.database import DatabaseClient
from api.clients.sim import SimClient, SimSettings
from api.config import AppConfig
from api.db.tables import ClipRow
from api.models.clip import ACTIVE_CLIP_STATUSES, CLIP_VIEWS, Clip, ClipOffset, ClipOutcome, ClipRequest, ClipView
from api.models.design import Design
from api.models.finger import build_finger
from api.models.job import Job, Trial
from api.services import cell_profiles, compute, jobs, results

logger = logging.getLogger(__name__)

SAME_OFFSET_MM = 1e-6  # offsets this close are the same grid point


class ClipNotFoundError(LookupError):
    pass


class ClipsUnavailableError(RuntimeError):
    """The experiment can't be filmed: it ran on the mock sim."""


class ClipNotReadyError(RuntimeError):
    """The clip has no video (yet): it's still queued or recording, it failed, or it lacks that view."""


def request_clip(db: DatabaseClient, config: AppConfig, job_id: str, request: ClipRequest) -> Clip:
    """Ask for a clip of a final design (D1, ..., STOCK, IMP) at one offset, and start its worker. Raises
    results.ResultsNotReadyError before the final test, results.DesignNotFoundError for an unknown label,
    ClipsUnavailableError for a mock experiment and compute.ComputeNotReadyError without a ready GPU."""
    job, trial = results.final_trial(db, job_id, request.design)
    if job.sim_backend != "isaac":
        raise ClipsUnavailableError(
            f"{job.experiment_id} ran on the mock sim, which has no physics or cameras to film a grasp with: clips need an "
            "experiment run on the Isaac sim"
        )
    existing = _find(db, job_id, trial.label, request.offset)
    if existing is not None and existing.status != "failed":
        return existing
    compute.claim(db, config)
    with db.session() as s:
        row = ClipRow(
            job_id=job_id,
            design=trial.label,
            dx=request.offset.dx,
            dy=request.offset.dy,
            yaw_deg=request.offset.yaw_deg,
            status="queued",
            views=list(CLIP_VIEWS),
        )
        s.add(row)
        s.flush()
        clip_id = row.id
    try:
        _update(db, clip_id, pid=jobs.spawn_worker(db, config, job_id, "clip", str(clip_id)))
    except OSError as e:
        logger.exception("Clip %d: couldn't start its worker", clip_id)
        _update(db, clip_id, status="failed", error=f"couldn't start the recording worker: {e}")
    logger.info("Job %s: clip %d of %s at %s requested", job_id, clip_id, trial.label, request.offset.model_dump())
    return get_clip(db, job_id, clip_id)


def list_clips(db: DatabaseClient, job_id: str) -> list[Clip]:
    """The experiment's clips, newest first."""
    jobs.get_job(db, job_id)
    with db.session() as s:
        rows = s.scalars(select(ClipRow).where(ClipRow.job_id == job_id).order_by(ClipRow.id.desc()))
        return [_clip(row) for row in rows]


def get_clip(db: DatabaseClient, job_id: str, clip_id: int) -> Clip:
    with db.session() as s:
        row = s.get(ClipRow, clip_id)
        if row is None or row.job_id != job_id:
            raise ClipNotFoundError(f"job {job_id} has no clip {clip_id}")
        return _clip(row)


def clip_video(db: DatabaseClient, config: AppConfig, job_id: str, clip_id: int, view: ClipView) -> Path:
    """The mp4 of one view of a ready clip."""
    clip = get_clip(db, job_id, clip_id)
    if clip.status != "ready":
        raise ClipNotReadyError(f"clip {clip_id} is {clip.status}" + (f": {clip.error}" if clip.error else ""))
    path = video_path(config.outputs_dir, job_id, clip_id, view)
    if view not in clip.views or not path.is_file():
        raise ClipNotReadyError(f"clip {clip_id} has no {view} video")
    return path


def video_path(outputs_dir: Path, job_id: str, clip_id: int, view: str) -> Path:
    return outputs_dir / job_id / "clips" / f"{clip_id}_{view}.mp4"


def record_clip(db: DatabaseClient, clip_id: int, *, sim: SimClient, outputs_dir: Path) -> None:
    """The worker's part: film the clip and store it. A failure is stored on the clip (status failed, error), not
    raised. A clip that's already ready or failed is left alone."""
    with db.session() as s:
        row = s.get(ClipRow, clip_id)
        if row is None:
            logger.error("Clip %d: not found", clip_id)
            return
        clip = _clip(row)
    if clip.status not in ACTIVE_CLIP_STATUSES:
        logger.info("Clip %d is already %s", clip_id, clip.status)
        return
    _update(db, clip_id, status="recording", pid=os.getpid(), error=None)
    started = time.time()
    try:
        job, trial = results.final_trial(db, clip.job_id, clip.design)
        gripper = cell_profiles.get_profile(db, job.cell_profile_id).profile.gripper
        design = Design(kind=trial.kind, params=trial.params)
        finger = None if design.kind == "stock" else build_finger(job.part, design, gripper)  # None: the robot's own fingers
        settings = SimSettings(grip_force_n=job.plan.grip_force_n, transport=job.spec.task.transport)
        recording = sim.record(job.part, finger, clip.offset.model_dump(), settings, list(clip.views))
        for view, data in recording.videos.items():
            path = video_path(outputs_dir, job.id, clip_id, view)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        _update(
            db,
            clip_id,
            status="ready",
            outcome="held" if recording.held else "missed",
            result=_stored_outcome(job, trial, clip.offset),
            views=[view for view in CLIP_VIEWS if view in recording.videos],
            duration_s=recording.duration_s,
            recorded=time.time(),
        )
        logger.info("Clip %d (%s, %s): recorded in %.0f s", clip_id, clip.job_id, clip.design, time.time() - started)
    except Exception as e:
        logger.exception("Clip %d: recording failed", clip_id)
        line = next((text.strip() for text in str(e).splitlines() if text.strip()), type(e).__name__)
        _update(db, clip_id, status="failed", error=line[:300])


def _stored_outcome(job: Job, trial: Trial, offset: ClipOffset) -> ClipOutcome | None:
    """Whether the job's final test held the part at this offset; None when it isn't a point of the final grid."""
    for i, point in enumerate(job.plan.final_grid.points()):
        if (
            abs(point["dx"] - offset.dx) <= SAME_OFFSET_MM
            and abs(point["dy"] - offset.dy) <= SAME_OFFSET_MM
            and abs(point["yaw_deg"] - offset.yaw_deg) <= SAME_OFFSET_MM
        ):
            return "held" if trial.held[i] else "missed"
    return None


def _find(db: DatabaseClient, job_id: str, design: str, offset: ClipOffset) -> Clip | None:
    """The newest clip of this design at this offset."""
    with db.session() as s:
        rows = s.scalars(select(ClipRow).where(ClipRow.job_id == job_id, ClipRow.design == design).order_by(ClipRow.id.desc()))
        for row in rows:
            if (
                abs(row.dx - offset.dx) <= SAME_OFFSET_MM
                and abs(row.dy - offset.dy) <= SAME_OFFSET_MM
                and abs(row.yaw_deg - offset.yaw_deg) <= SAME_OFFSET_MM
            ):
                return _clip(row)
    return None


def _clip(row: ClipRow) -> Clip:
    matches = None if row.outcome is None or row.result is None else row.outcome == row.result
    return Clip(
        id=row.id,
        job_id=row.job_id,
        design=row.design,
        offset=ClipOffset(dx=row.dx, dy=row.dy, yaw_deg=row.yaw_deg),
        status=row.status,
        views=row.views,
        outcome=row.outcome,
        result=row.result,
        matches_result=matches,
        duration_s=row.duration_s,
        error=row.error,
        created=row.created,
        recorded=row.recorded,
    )


def _update(db: DatabaseClient, clip_id: int, **values: Any) -> None:
    with db.session() as s:
        row = s.get(ClipRow, clip_id)
        for name, value in values.items():
            setattr(row, name, value)
