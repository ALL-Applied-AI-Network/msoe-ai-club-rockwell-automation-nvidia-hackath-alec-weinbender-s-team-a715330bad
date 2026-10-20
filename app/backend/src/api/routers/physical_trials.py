"""Logged physical trials (results tracker): the quick log of one trial, predicted vs measured, and the exports.

The quick log follows the spreadsheet upload's rules (services/physical_trials.py): a trial_id logs that planned trial
(logging it again overwrites it and keeps the old value in its history); without one, it's an extra trial and needs its
design and offset. 422 says why a trial can't be logged.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.dependencies import DbDep
from api.models.physical_trial import PhysicalTrial, TrialOutcome
from api.models.validation import Validation
from api.services import jobs, physical_trials, printed_fingers, test_plans

router = APIRouter(prefix="/api", tags=["physical trials"])


class LogTrialRequest(BaseModel):
    """One trial: a planned one by trial_id, or an extra (trial_id left out) with design_label and the offset."""

    trial_id: str | None = None  # T0042
    plan_id: int | None = None  # an extra's plan; with a trial_id, it must be that trial's plan
    design_label: str | None = None  # extras; checked against the plan when given with a trial_id
    offset_x_mm: float | None = None
    offset_y_mm: float | None = None
    yaw_deg: float | None = None  # extras: 0 if left out
    repeat: int | None = Field(None, ge=1)
    finger_id: str | None = None  # the fingers used; left out: the design's printed pair, if recorded
    outcome: TrialOutcome
    in_tolerance: bool | None = None  # place and insert: whether the part sat within the task's tolerance
    notes: str = Field("", max_length=2000)
    video_link: str | None = None
    operator: str | None = None
    timestamp: datetime | None = None  # left out: now


@router.post("/jobs/{job_id}/physical")
def log_trial(job_id: str, body: LogTrialRequest, db: DbDep) -> PhysicalTrial:
    """Log one trial by hand. Returns it as stored (with its new trial_id, for an extra)."""
    values = body.model_dump(exclude={"plan_id"})
    if body.timestamp is not None:
        values["timestamp"] = body.timestamp.isoformat(timespec="seconds")
    with _http_errors():
        return physical_trials.log_trial(db, job_id, values, plan_id=body.plan_id)


@router.get("/jobs/{job_id}/physical")
def list_trials(job_id: str, db: DbDep) -> list[PhysicalTrial]:
    """Every trial logged for the job, in the order logged."""
    with _http_errors():
        printed_fingers.load_job(db, job_id)
        return physical_trials.list_trials(db, job_id)


@router.get("/jobs/{job_id}/validation")
def get_validation(job_id: str, db: DbDep) -> Validation:
    """Predicted vs measured per tested design, the mismatch map, the measured points for the success curve, and the
    physical badge."""
    with _http_errors():
        return physical_trials.validation(db, job_id)


@router.get("/export/physical.jsonl", response_class=Response, responses={200: {"content": {"application/x-ndjson": {}}}})
def export_jsonl(db: DbDep, job_id: str | None = None) -> Response:
    """Every logged trial (of one job, or all), one JSON object per line, with the sim's prediction for it."""
    with _http_errors():
        rows = physical_trials.export_rows(db, job_id)
        name = physical_trials.export_file_name(db, job_id, "jsonl")
    body = "".join(f"{json.dumps(row)}\n" for row in rows)
    return Response(body, media_type="application/x-ndjson", headers=_attachment(name))


@router.get("/export/physical.csv", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def export_csv(db: DbDep, job_id: str | None = None) -> Response:
    """The same rows as CSV: booleans as true / false, history as JSON text."""
    with _http_errors():
        content = physical_trials.export_csv(db, job_id)
        name = physical_trials.export_file_name(db, job_id, "csv")
    return Response(content, media_type="text/csv; charset=utf-8", headers=_attachment(name))


def _attachment(name: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except jobs.JobNotFoundError as e:
        raise HTTPException(404, f"job {e} not found") from None
    except test_plans.TestPlanNotFoundError as e:
        raise HTTPException(404, f"test plan {e} not found") from None
    except printed_fingers.JobNotDoneError as e:
        raise HTTPException(409, str(e)) from None
    except physical_trials.PhysicalTrialError as e:
        raise HTTPException(422, str(e)) from None
