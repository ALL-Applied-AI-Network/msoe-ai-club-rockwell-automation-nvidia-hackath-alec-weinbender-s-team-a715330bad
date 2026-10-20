"""Isaac Sim clips of a finished experiment's final designs: ask for one, list them, play one.

A new clip comes back with status "queued"; a worker films it, and it reads "recording", then "ready" (or "failed", with
error). Poll the list until then. The first clip after the sim server starts takes longer, while its render materials
compile. Only experiments run on the Isaac sim can be filmed, and filming needs a ready GPU, like a job.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from api.dependencies import ConfigDep, DbDep
from api.models.clip import Clip, ClipRequest, ClipView
from api.services import clips, compute, jobs, results

router = APIRouter(prefix="/api/jobs", tags=["clips"])


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except (jobs.JobNotFoundError, results.DesignNotFoundError, clips.ClipNotFoundError) as e:
        raise HTTPException(404, str(e)) from None
    except (results.ResultsNotReadyError, clips.ClipsUnavailableError, clips.ClipNotReadyError, compute.ComputeNotReadyError) as e:
        raise HTTPException(409, str(e)) from None


@router.post("/{job_id}/clips", status_code=202)
def request_clip(job_id: str, request: ClipRequest, db: DbDep, config: ConfigDep) -> Clip:
    """Film a final design (D1, ..., STOCK, IMP; any case) at one offset, in mm and degrees as the results' grid points
    give them. 202 with the clip, queued; the same design and offset again returns its existing clip, unless that one
    failed. 404 for an unknown job or label; 409 before the final test, for a mock experiment, or when no GPU is ready
    (the message says which)."""
    with _http_errors():
        return clips.request_clip(db, config, job_id, request)


@router.get("/{job_id}/clips")
def list_clips(job_id: str, db: DbDep) -> list[Clip]:
    """The experiment's clips, newest first."""
    with _http_errors():
        return clips.list_clips(db, job_id)


@router.get(
    "/{job_id}/clips/{clip_id:int}.mp4",
    response_class=FileResponse,
    responses={200: {"content": {"video/mp4": {}}}},
)
def clip_video(job_id: str, clip_id: int, db: DbDep, config: ConfigDep, view: ClipView = "closeup") -> FileResponse:
    """One view's video (H.264 mp4, about 5 s) of a ready clip. 409 while it isn't ready, or when it lacks the view."""
    with _http_errors():
        path = clips.clip_video(db, config, job_id, clip_id, view)
    return FileResponse(path, media_type="video/mp4", filename=path.name)
