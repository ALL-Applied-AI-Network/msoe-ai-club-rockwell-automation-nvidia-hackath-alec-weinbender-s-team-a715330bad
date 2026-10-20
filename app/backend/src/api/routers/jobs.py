"""Experiments: plan, create, list (cards), live progress, results, re-score, downloads, and the review gate.

A blocked spec is refused with 422 and {message, reasons, failed_step, blockers}: each blocker names the input step whose
screen fixes it. A blocked export (a failed blocking check) is refused with 409 and {message, failed_checks}. The CAD work
(planning builds fingers, downloads export them) runs in a thread, so it never blocks the event loop.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import CadDep, ConfigDep, DbDep
from api.models.error_model import ErrorModel
from api.models.export_check import ExportCheck
from api.models.job import FINISHED_STATUSES, Job, JobStatus
from api.models.job_spec import JobSpec, SimBackend
from api.models.results import FingerPreview, JobCard, ResultsView, grasp_pose_text, slug
from api.models.review import Review
from api.models.search_plan import JobPlan
from api.models.task import Task
from api.services import jobs, results, reviews

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

EVENT_POLL_S = 1.0
MEDIA_TYPES = {"step": "model/step", "stl_left": "model/stl", "stl_right": "model/stl", "print_sheet": "application/pdf"}


class PlanResponse(JobPlan):
    failed_step: int | None  # the earliest input step with a blocker; None when the job can run


class CreateJobRequest(JobSpec):
    duplicated_from: str | None = None  # the job this spec was duplicated from, if any


class CreateJobResponse(BaseModel):
    id: str
    experiment_id: str
    name: str


class JobDetailResponse(Job):
    card: JobCard
    review: Review | None


class RenameJobRequest(BaseModel):
    name: str = Field(min_length=1, max_length=jobs.MAX_NAME)


class RescoreRequest(BaseModel):
    """Score the stored outcomes at another error model or task; either left out keeps the job's own."""

    error: ErrorModel | None = None
    task: Task | None = None


class ChecksResponse(BaseModel):
    label: str
    checks: list[ExportCheck]
    blocked: bool  # a blocking check failed: the files can't be downloaded
    files: list[str]  # what's there to download: "step", "stl_left", "stl_right", "print_sheet"


class ReviewRequest(BaseModel):
    status: str  # approved, rejected or pending
    reviewer: str = ""
    notes: str = ""


class OkResponse(BaseModel):
    ok: bool = True


@router.post("/plan")
async def plan_job(spec: JobSpec, db: DbDep, config: ConfigDep) -> PlanResponse:
    """Steps 6-8: the plan for a spec (searches, totals, time estimate, warnings), stored nowhere. Always 200: what
    blocks the job is in blocked / blockers, each with the input step that fixes it."""
    planned = await run_in_threadpool(jobs.plan_spec, db, config, spec)
    plan = planned.plan
    return PlanResponse(**plan.model_dump(), failed_step=min((b.step for b in plan.blockers), default=None))


@router.post("", status_code=201)
async def create_job(body: CreateJobRequest, db: DbDep, config: ConfigDep) -> CreateJobResponse:
    """Step 8: store the experiment and start its run. 422 with the blockers if the spec can't run yet."""
    spec = JobSpec.model_validate(body.model_dump(exclude={"duplicated_from"}))
    with _http_errors():
        job = await run_in_threadpool(lambda: jobs.create_job(db, config, spec, duplicated_from=body.duplicated_from))
    return CreateJobResponse(id=job.id, experiment_id=job.experiment_id, name=job.name)


@router.get("")
def list_jobs(db: DbDep, part_id: str | None = None, status: JobStatus | None = None, backend: SimBackend | None = None) -> list[JobCard]:
    """The job list: cards, newest first."""
    return jobs.job_cards(db, part_id=part_id, status=status, backend=backend)


@router.get("/{job_id}")
def get_job(job_id: str, db: DbDep) -> JobDetailResponse:
    """The job with its spec, posed part and plan, its card, and its review."""
    with _http_errors():
        job = jobs.get_job(db, job_id)
        card = jobs.job_card(db, job_id)
    return JobDetailResponse(**job.model_dump(), card=card, review=reviews.get_review(db, job_id))


@router.patch("/{job_id}")
def rename_job(job_id: str, body: RenameJobRequest, db: DbDep) -> JobCard:
    """Rename the experiment. Its experiment ID never changes."""
    with _http_errors():
        jobs.rename_job(db, job_id, body.name)
        return jobs.job_card(db, job_id)


@router.post("/{job_id}/duplicate")
def duplicate_job(job_id: str, db: DbDep) -> JobSpec:
    """A copy of the job's spec named "<name> (copy)", for the wizard to edit and POST /api/jobs with duplicated_from.
    Nothing is stored or started."""
    with _http_errors():
        return jobs.duplicate_job(db, job_id)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: DbDep) -> OkResponse:
    with _http_errors():
        jobs.cancel_job(db, job_id)
    return OkResponse()


@router.post("/{job_id}/resume")
def resume_job(job_id: str, db: DbDep, config: ConfigDep) -> OkResponse:
    """Restart an interrupted, cancelled or failed job after its last checkpointed round (409 for any other status)."""
    with _http_errors():
        jobs.resume_job(db, config, job_id)
    return OkResponse()


@router.get("/{job_id}/events")
async def job_events(job_id: str, db: DbDep) -> StreamingResponse:
    """Server-sent events: the job's card each time it changes, ending once the job is finished (done, failed,
    cancelled or interrupted)."""
    with _http_errors():
        await run_in_threadpool(jobs.get_job, db, job_id)

    async def stream():
        last = None
        while True:
            try:
                card = await run_in_threadpool(jobs.job_card, db, job_id)
            except jobs.JobNotFoundError:
                return
            event = card.model_dump_json()
            if event != last:
                yield f"data: {event}\n\n"
                last = event
            if card.status in FINISHED_STATUSES:
                return
            await asyncio.sleep(EVENT_POLL_S)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/{job_id}/results")
def get_results(job_id: str, db: DbDep) -> ResultsView:
    """The results page at the job's own error model and task. The final-test sections are null until it has run."""
    with _http_errors():
        return results.results(db, job_id)


@router.post("/{job_id}/rescore")
def rescore(job_id: str, body: RescoreRequest, db: DbDep) -> ResultsView:
    """The results page at another error model and/or task, from the stored outcomes: nothing is simulated or stored."""
    with _http_errors():
        return results.results(db, job_id, error=body.error, task=body.task)


@router.get("/{job_id}/finger")
async def get_finger(job_id: str, db: DbDep, design: str = "D1") -> FingerPreview:
    """Both fingers of a final design (D1 by default) and the part, for the 3D preview."""
    with _http_errors():
        return await run_in_threadpool(results.finger_preview, db, job_id, design)


@router.get("/{job_id}/designs/{label}/cad", response_class=FileResponse)
async def download_cad(
    job_id: str,
    label: str,
    db: DbDep,
    config: ConfigDep,
    cad: CadDep,
    format: Literal["step", "stl"] = "step",
    side: Literal["L", "R"] = "L",
) -> FileResponse:
    """The pair as one STEP, or one finger as an STL lying in its print orientation. 409 with the failed checks if the
    export is blocked, 422 for STOCK."""
    key = "step" if format == "step" else {"L": "stl_left", "R": "stl_right"}[side]
    return await _download(db, config, cad, job_id, label, key)


@router.get("/{job_id}/designs/{label}/print-sheet.pdf", response_class=FileResponse)
async def download_print_sheet(job_id: str, label: str, db: DbDep, config: ConfigDep, cad: CadDep) -> FileResponse:
    return await _download(db, config, cad, job_id, label, "print_sheet")


@router.get("/{job_id}/designs/{label}/checks")
async def export_checks(job_id: str, label: str, db: DbDep, config: ConfigDep, cad: CadDep) -> ChecksResponse:
    """The export checks of a final design (exporting it first if it hasn't been yet): never blocked, it's where to see
    why a download is."""
    with _http_errors():
        export = await run_in_threadpool(lambda: results.design_export(db, job_id, label, cad=cad, outputs_dir=config.outputs_dir))
    return ChecksResponse(label=export.label, checks=export.checks, blocked=bool(export.blocked), files=sorted(export.files))


@router.get("/{job_id}/designs/{label}/grasp-pose")
async def get_grasp_pose(job_id: str, label: str, db: DbDep, format: Literal["json", "text"] = "json") -> Any:
    """The grasp to give the robot with a final design, as JSON or as copyable "key: value" text."""
    with _http_errors():
        pose = await run_in_threadpool(results.grasp_pose, db, job_id, label)
    if format == "text":
        return PlainTextResponse(grasp_pose_text(pose))
    return JSONResponse(pose)


@router.get("/{job_id}/run-metadata.json")
def run_metadata(job_id: str, db: DbDep) -> JSONResponse:
    """What the run used: versions, GPU, grids, seed, sim backend and its settings, cell profile, plan, stop reasons."""
    with _http_errors():
        job = jobs.get_job(db, job_id)
        meta = results.run_metadata(db, job_id)
    filename = f"{slug(job.name)}_{job.experiment_id}_run-metadata.json"
    return JSONResponse(meta, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/{job_id}/review")
def review_job(job_id: str, form: Annotated[ReviewRequest, Form()], db: DbDep) -> OkResponse:
    """The safety gate. A finger can only be approved under a reviewer's name."""
    try:
        reviews.set_review(db, job_id, status=form.status, reviewer=form.reviewer, notes=form.notes)
    except reviews.ReviewError as e:
        raise HTTPException(422, str(e)) from None
    return OkResponse()


async def _download(db, config, cad, job_id: str, label: str, key: str) -> FileResponse:
    with _http_errors():
        path, filename = await run_in_threadpool(
            lambda: results.design_file(db, job_id, label, key, cad=cad, outputs_dir=config.outputs_dir)
        )
    return FileResponse(path, media_type=MEDIA_TYPES[key], filename=filename)


@contextmanager
def _http_errors() -> Iterator[None]:
    """The services' domain errors as HTTP errors."""
    try:
        yield
    except (jobs.JobNotFoundError, results.DesignNotFoundError) as e:
        raise HTTPException(404, str(e) or "not found") from None
    except (jobs.JobNotResumableError, results.ResultsNotReadyError) as e:
        raise HTTPException(409, str(e)) from None
    except results.ExportBlockedError as e:
        raise HTTPException(409, {"message": str(e), "failed_checks": [c.model_dump() for c in e.checks]}) from None
    except jobs.JobBlockedError as e:
        detail = {"message": str(e), "reasons": [b.reason for b in e.blockers], "failed_step": e.failed_step}
        raise HTTPException(422, detail | {"blockers": [b.model_dump() for b in e.blockers]}) from None
    except (jobs.JobInputError, results.DesignNotExportableError) as e:
        raise HTTPException(422, str(e)) from None
