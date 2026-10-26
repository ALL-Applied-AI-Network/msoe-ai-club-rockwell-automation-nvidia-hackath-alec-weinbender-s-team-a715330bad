"""Qualifications: one library finger on one part, the sim's prediction for the pair and the real robot's sessions.

Evaluation jobs create and update them as they finish. Sessions can also be logged for a pair no evaluation has covered:
POST /api/qualifications with the finger and part first.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import DbDep
from api.models.qualification import QualificationView, SessionKind
from api.services import qualifications

router = APIRouter(prefix="/api/qualifications", tags=["qualifications"])


class CreateQualificationRequest(BaseModel):
    finger_id: str
    part_id: str


class SessionRequest(BaseModel):
    """A real-robot session: how many grasps were tried, and how many succeeded. natural: the cell running as usual,
    compared with the pair's prediction; commanded: deliberate offsets (our platform runs), compared with
    predicted_success, the sim's rate at those offsets."""

    kind: SessionKind = "natural"
    trials: int = Field(ge=1)
    successes: int = Field(ge=0)
    predicted_success: float | None = Field(None, ge=0, le=1)
    notes: str = ""
    operator: str | None = None
    date: str | None = None  # ISO


class UpdateSessionRequest(BaseModel):
    """Only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    kind: SessionKind | None = None
    trials: int | None = Field(None, ge=1)
    successes: int | None = Field(None, ge=0)
    predicted_success: float | None = Field(None, ge=0, le=1)
    notes: str | None = None
    operator: str | None = None
    date: str | None = None


@router.get("")
def list_qualifications(db: DbDep, finger_id: str | None = None, part_id: str | None = None) -> list[QualificationView]:
    """Every finger-and-part pair, filtered by finger and/or part, most recently updated first."""
    return qualifications.list_qualifications(db, finger_id=finger_id, part_id=part_id)


@router.post("", status_code=201)
def create_qualification(body: CreateQualificationRequest, db: DbDep) -> QualificationView:
    """The pair's qualification, created without a prediction if no evaluation has covered it yet (returned as it is
    if one has)."""
    with _http_errors():
        return qualifications.ensure_qualification(db, body.finger_id, body.part_id)


@router.get("/{qualification_id}")
def get_qualification(qualification_id: int, db: DbDep) -> QualificationView:
    with _http_errors():
        return qualifications.get_qualification(db, qualification_id)


@router.post("/{qualification_id}/sessions", status_code=201)
def add_session(qualification_id: int, body: SessionRequest, db: DbDep) -> QualificationView:
    """Log a real-robot session. The pair is validated from its first session; its gap is flagged when the sim's
    prediction falls outside the 95% Wilson interval of what was measured."""
    with _http_errors():
        return qualifications.add_session(db, qualification_id, **body.model_dump())


@router.patch("/{qualification_id}/sessions/{session_id}")
def update_session(qualification_id: int, session_id: int, body: UpdateSessionRequest, db: DbDep) -> QualificationView:
    with _http_errors():
        return qualifications.update_session(db, qualification_id, session_id, body.model_dump(exclude_unset=True))


@router.delete("/{qualification_id}/sessions/{session_id}")
def delete_session(qualification_id: int, session_id: int, db: DbDep) -> QualificationView:
    with _http_errors():
        return qualifications.delete_session(db, qualification_id, session_id)


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except qualifications.QualificationNotFoundError as e:
        raise HTTPException(404, f"qualification {e} not found") from None
    except qualifications.SessionNotFoundError as e:
        raise HTTPException(404, f"session {e} not found") from None
    except qualifications.QualificationInputError as e:
        raise HTTPException(422, str(e)) from None
