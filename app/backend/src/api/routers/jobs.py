import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from api.dependencies import ConfigDep, DbDep
from api.models.job import FINISHED_STATUSES, Job, JobConfig, JobResult, Suggestion, Trial
from api.models.part import Part
from api.models.physical_trial import PhysicalTrial
from api.models.review import Review
from api.services import jobs, physical_trials, reviews

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

EVENT_POLL_S = 1.0


class CreateJobRequest(Part, JobConfig):
    """The new-job form: the part, the search settings, the task text and an optional CAD file of the part."""

    task: str
    part_file: UploadFile | None = None


class CreateJobResponse(BaseModel):
    id: str


class JobResponse(Job):
    progress: float  # n_done / n_total

    @classmethod
    def from_job(cls, job: Job, **extra) -> "JobResponse":
        return cls(**job.model_dump(), progress=job.n_done / job.n_total if job.n_total else 0, **extra)


class JobDetailResponse(JobResponse):
    suggestions: list[Suggestion]
    trials: list[Trial]
    result: JobResult | None
    meta: dict[str, Any] | None
    review: Review | None
    physical: list[PhysicalTrial]


class JobEvent(BaseModel):
    """One server-sent event: the job's progress fields."""

    status: str
    stage: str | None
    n_done: int
    n_total: int
    best_value: float | None


class ReviewRequest(BaseModel):
    status: str  # approved, rejected or pending
    reviewer: str = ""
    notes: str = ""


class PhysicalTrialRequest(BaseModel):
    finger: str = "optimized"
    success: int
    placement_error_mm: float | None = None
    cycle_time_s: float | None = None
    recovered: int = 0
    operator_intervention: int = 0
    notes: str = ""


class OkResponse(BaseModel):
    ok: bool = True


@router.post("")
async def create_job(form: Annotated[CreateJobRequest, Form()], db: DbDep, config: ConfigDep) -> CreateJobResponse:
    f = form.part_file
    upload = (f.filename, await f.read()) if f and f.filename else None
    job_id = jobs.create_job(
        db,
        config,
        task=form.task,
        part=Part.model_validate(form.model_dump(include=set(Part.model_fields))),
        job_config=JobConfig.model_validate(form.model_dump(include=set(JobConfig.model_fields))),
        upload=upload,
    )
    return CreateJobResponse(id=job_id)


@router.get("")
def list_jobs(db: DbDep) -> list[JobResponse]:
    return [JobResponse.from_job(job) for job in jobs.list_jobs(db)]


@router.get("/{job_id}")
def get_job(job_id: str, db: DbDep) -> JobDetailResponse:
    try:
        detail = jobs.get_job_detail(db, job_id)
    except jobs.JobNotFoundError:
        raise HTTPException(404) from None
    return JobDetailResponse.from_job(detail.job, **detail.model_dump(exclude={"job"}))


@router.get("/{job_id}/events")
async def job_events(job_id: str, db: DbDep) -> StreamingResponse:
    """Server-sent events: pushes the job's progress so the UI updates live without polling logic of its own."""

    async def stream():
        last = None
        while True:
            try:
                job = jobs.get_job(db, job_id)
            except jobs.JobNotFoundError:
                return
            event = JobEvent.model_validate(job.model_dump()).model_dump_json()
            if event != last:
                yield f"data: {event}\n\n"
                last = event
            if job.status in FINISHED_STATUSES:
                return
            await asyncio.sleep(EVENT_POLL_S)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, db: DbDep) -> OkResponse:
    jobs.cancel_job(db, job_id)
    return OkResponse()


@router.post("/{job_id}/resume")
def resume_job(job_id: str, db: DbDep, config: ConfigDep) -> OkResponse:
    try:
        jobs.resume_job(db, config, job_id)
    except jobs.JobNotResumableError:
        raise HTTPException(409, "not resumable") from None
    return OkResponse()


@router.get("/{job_id}/scad")
def download_cad(job_id: str, db: DbDep) -> FileResponse:
    try:
        path = jobs.result_file(db, job_id)
    except jobs.JobNotFoundError:
        raise HTTPException(404) from None
    return FileResponse(path, filename=f"fingers_{job_id}{path.suffix}")


@router.post("/{job_id}/review")
def review_job(job_id: str, form: Annotated[ReviewRequest, Form()], db: DbDep) -> OkResponse:
    """The safety gate. A finger can only be approved under a reviewer's name."""
    try:
        reviews.set_review(db, job_id, status=form.status, reviewer=form.reviewer, notes=form.notes)
    except reviews.ReviewError as e:
        raise HTTPException(422, str(e)) from None
    return OkResponse()


@router.post("/{job_id}/physical")
def add_physical_trial(job_id: str, form: Annotated[PhysicalTrialRequest, Form()], db: DbDep) -> OkResponse:
    physical_trials.add_trial(db, job_id, **form.model_dump())
    return OkResponse()
