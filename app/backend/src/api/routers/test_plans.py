"""Physical test plans (results tracker): generate one for a finished job, read it with what's been logged against it,
download it as XLSX or CSV to fill in at the robot, and upload it back.

A new plan comes back with prediction_status "pending": a worker simulates every row, and the plan reads "done" (or
"failed", with prediction_error) when it's finished. Poll GET /{plan_id} until then. The upload applies every valid row
and reports the rest with their row numbers; it's 200 even when some rows have errors.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api.dependencies import ConfigDep, DbDep
from api.models.physical_trial import LogReport, PhysicalTrial
from api.models.test_plan import POINTWISE_REPEATS, RANDOM_PER_DESIGN, PredictionStatus, TestPlan
from api.services import jobs, physical_trials, printed_fingers, spreadsheets, test_plans

router = APIRouter(prefix="/api/jobs", tags=["test plans"])


class CreateTestPlanRequest(BaseModel):
    pointwise_repeats: int = Field(POINTWISE_REPEATS, ge=1, le=10)  # each of the 25 point-wise offsets, this many times
    random_per_design: int = Field(RANDOM_PER_DESIGN, ge=0, le=500)  # offsets drawn from the job's error model
    seed: int | None = Field(None, ge=0, le=2**32 - 1)  # for the random offsets; none: one is picked and stored


class TestPlanSummaryResponse(BaseModel):
    """A plan without its rows, for the list."""

    id: int
    job_id: str
    created: float
    seed: int
    designs: list[str]
    prediction_status: PredictionStatus
    prediction_error: str | None
    planned: int  # planned trials
    logged: int  # of those, with an outcome
    extras: int  # extra trials logged with this plan

    @classmethod
    def of(cls, plan: TestPlan, trials: list[PhysicalTrial]) -> "TestPlanSummaryResponse":
        logged, extras = _counts(plan, trials)
        return cls(**plan.model_dump(exclude={"rows"}), planned=len(plan.rows), logged=logged, extras=extras)


class TestPlanResponse(TestPlan):
    """The plan's rows, plus every trial logged with it: planned ones (match them to rows by trial_id) and its extras."""

    logged: int  # planned trials with an outcome
    extras: int
    logged_trials: list[PhysicalTrial]

    @classmethod
    def of(cls, plan: TestPlan, trials: list[PhysicalTrial]) -> "TestPlanResponse":
        logged, extras = _counts(plan, trials)
        return cls(**plan.model_dump(), logged=logged, extras=extras, logged_trials=trials)


class UploadResultsRequest(BaseModel):
    file: UploadFile  # the plan's .xlsx or .csv, filled in


class UploadResultsResponse(LogReport):
    pass


@router.post("/{job_id}/test-plans", status_code=201)
def create_test_plan(job_id: str, body: CreateTestPlanRequest, db: DbDep, config: ConfigDep) -> TestPlanResponse:
    """Plan the physical test of the print selection plus IMP and STOCK, and start predicting it. 409 if the job isn't
    done."""
    with _http_errors():
        plan = test_plans.create_test_plan(db, config, job_id, **body.model_dump())
    return TestPlanResponse.of(plan, [])


@router.get("/{job_id}/test-plans")
def list_test_plans(job_id: str, db: DbDep) -> list[TestPlanSummaryResponse]:
    with _http_errors():
        plans = test_plans.list_test_plans(db, job_id)
        trials = physical_trials.list_trials(db, job_id)
    return [TestPlanSummaryResponse.of(plan, [t for t in trials if t.plan_id == plan.id]) for plan in plans]


@router.get(
    "/{job_id}/test-plans/{plan_id:int}.xlsx", response_class=Response, responses={200: {"content": {spreadsheets.XLSX_MEDIA_TYPE: {}}}}
)
def download_xlsx(job_id: str, plan_id: int, db: DbDep) -> Response:
    """The plan to fill in: outcome (and, for place / insert, in_tolerance) dropdowns; the predicted column is hidden."""
    with _http_errors():
        name, content = test_plans.plan_xlsx(db, job_id, plan_id)
    return Response(content, media_type=spreadsheets.XLSX_MEDIA_TYPE, headers=_attachment(name))


@router.get("/{job_id}/test-plans/{plan_id:int}.csv", response_class=Response, responses={200: {"content": {"text/csv": {}}}})
def download_csv(job_id: str, plan_id: int, db: DbDep, include_predicted: bool = False) -> Response:
    """The same columns as the XLSX; predicted is blank unless include_predicted=true."""
    with _http_errors():
        name, content = test_plans.plan_csv(db, job_id, plan_id, include_predicted=include_predicted)
    return Response(content, media_type="text/csv; charset=utf-8", headers=_attachment(name))


@router.get("/{job_id}/test-plans/{plan_id:int}")
def get_test_plan(job_id: str, plan_id: int, db: DbDep) -> TestPlanResponse:
    with _http_errors():
        plan = test_plans.get_test_plan(db, job_id, plan_id)
        trials = physical_trials.list_trials(db, job_id, plan_id=plan_id)
    return TestPlanResponse.of(plan, trials)


@router.post("/{job_id}/test-plans/{plan_id:int}/predict")
def predict_again(job_id: str, plan_id: int, db: DbDep, config: ConfigDep) -> TestPlanResponse:
    """Start predicting the plan again (after a failure, say). Its offsets and trial IDs don't change."""
    with _http_errors():
        plan = test_plans.predict_again(db, config, job_id, plan_id)
        trials = physical_trials.list_trials(db, job_id, plan_id=plan_id)
    return TestPlanResponse.of(plan, trials)


@router.post("/{job_id}/test-plans/{plan_id:int}/upload")
async def upload_results(job_id: str, plan_id: int, form: Annotated[UploadResultsRequest, Form()], db: DbDep) -> UploadResultsResponse:
    """Log a filled-in plan. 415 for a file that isn't .xlsx or .csv; 422 if it can't be read as the plan's table."""
    content = await form.file.read(spreadsheets.MAX_UPLOAD_BYTES + 1)  # one byte over is enough to refuse it
    with _http_errors():
        report = await run_in_threadpool(physical_trials.upload_results, db, job_id, plan_id, form.file.filename or "", content)
    return UploadResultsResponse(**report.model_dump())


def _counts(plan: TestPlan, trials: list[PhysicalTrial]) -> tuple[int, int]:
    """(planned trials with an outcome, extra trials) among the trials logged with this plan."""
    planned = {row.trial_id for row in plan.rows}
    return sum(1 for t in trials if t.trial_id in planned), sum(1 for t in trials if t.kind == "extra")


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
    except spreadsheets.UnsupportedSpreadsheetError as e:
        raise HTTPException(415, str(e)) from None
    except (test_plans.TestPlanError, spreadsheets.SpreadsheetError) as e:
        raise HTTPException(422, str(e)) from None
