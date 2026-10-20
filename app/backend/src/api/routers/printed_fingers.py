"""An experiment's print selection and its printed fingers (results tracker). Both need the job done: designs get their
labels (D1, D2, ..., IMP, STOCK) from the final test.

STOCK and IMP are always tested as baselines, so they're never part of the selection itself; IMP is printed like the
chosen designs, STOCK is the aluminium fingers already on the robot.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import DbDep
from api.models.printed_finger import PrintedFinger, PrintSelection, Side
from api.services import jobs, printed_fingers

router = APIRouter(prefix="/api/jobs", tags=["printed fingers"])


class PrintSelectionRequest(BaseModel):
    designs: list[str]  # final-table labels, e.g. ["D1", "D3"]; STOCK and IMP are dropped (always tested)


class CreatePrintedFingerRequest(BaseModel):
    design_label: str = Field(min_length=1)  # D1, ..., or IMP
    side: Side = "pair"  # L, R, or a pair recorded together
    material: str = Field(min_length=1, max_length=60)  # e.g. "PLA": should match the friction the sim assumed
    print_date: date | None = None
    notes: str = Field("", max_length=2000)


@router.get("/{job_id}/print-selection")
def get_print_selection(job_id: str, db: DbDep) -> PrintSelection:
    with _http_errors():
        return printed_fingers.get_print_selection(db, job_id)


@router.put("/{job_id}/print-selection")
def set_print_selection(job_id: str, body: PrintSelectionRequest, db: DbDep) -> PrintSelection:
    """Choose the designs to print. 422 names any label the final test doesn't have; 409 if the job isn't done."""
    with _http_errors():
        return printed_fingers.set_print_selection(db, job_id, body.designs)


@router.get("/{job_id}/printed-fingers")
def list_printed_fingers(job_id: str, db: DbDep) -> list[PrintedFinger]:
    with _http_errors():
        return printed_fingers.list_printed_fingers(db, job_id)


@router.post("/{job_id}/printed-fingers", status_code=201)
def add_printed_finger(job_id: str, body: CreatePrintedFingerRequest, db: DbDep) -> PrintedFinger:
    """Record a printed finger (or pair). finger_id is the ID engraved on it, e.g. EXP-0042-D1-L."""
    with _http_errors():
        return printed_fingers.add_printed_finger(db, job_id, **body.model_dump())


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except jobs.JobNotFoundError as e:
        raise HTTPException(404, f"job {e} not found") from None
    except printed_fingers.JobNotDoneError as e:
        raise HTTPException(409, str(e)) from None
    except (printed_fingers.DesignLabelError, printed_fingers.PrintedFingerError) as e:
        raise HTTPException(422, str(e)) from None
