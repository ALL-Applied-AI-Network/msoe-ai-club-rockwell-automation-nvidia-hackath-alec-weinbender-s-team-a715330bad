"""Qualifications: one library finger on one part, the sim's prediction and the real robot's sessions (api/models/
qualification.py). Evaluation jobs write the predictions as they finish (record_predictions, in their own transaction);
the robotics engineer logs sessions here, for a pair an evaluation has covered or any other pair."""

import logging
import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from api.clients.database import DatabaseClient
from api.db.tables import FingerRow, PartRow, QualificationRow, RealSessionRow
from api.models.finger_record import finger_code
from api.models.qualification import Prediction, Qualification, QualificationView, RealSession, SessionKind, compare

logger = logging.getLogger(__name__)

SESSION_FIELDS = {"kind", "trials", "successes", "predicted_success", "notes", "operator", "date"}


class QualificationNotFoundError(LookupError):
    pass


class SessionNotFoundError(LookupError):
    pass


class QualificationInputError(ValueError):
    """A session or pair that can't be stored as asked: more successes than trials, an unknown finger or part."""


def record_predictions(s, part_id: str, predictions: dict[str, Prediction]) -> None:
    """Store each finger's prediction on the part, inside the caller's session `s` (an evaluation job's last
    transaction). A pair's previous prediction from another job moves to its history; one from the same job (its final
    test run again) is replaced."""
    now = time.time()
    for finger_id, prediction in predictions.items():
        row = s.scalar(select(QualificationRow).where(QualificationRow.finger_id == finger_id, QualificationRow.part_id == part_id))
        if row is None:
            s.add(QualificationRow(finger_id=finger_id, part_id=part_id, prediction=prediction, history=[], created=now, updated=now))
            continue
        if row.prediction is not None and row.prediction.job_id != prediction.job_id:
            row.history = [*row.history, row.prediction]
        row.prediction, row.updated = prediction, now


def ensure_qualification(db: DatabaseClient, finger_id: str, part_id: str) -> QualificationView:
    """The pair's qualification, created (with no prediction) if no evaluation has covered it yet, so real sessions can
    be logged for it."""
    with db.session() as s:
        if s.get(FingerRow, finger_id) is None:
            raise QualificationInputError(f"finger {finger_id} isn't in the library")
        if s.get(PartRow, part_id) is None:
            raise QualificationInputError(f"part {part_id} doesn't exist")
        row = s.scalar(select(QualificationRow).where(QualificationRow.finger_id == finger_id, QualificationRow.part_id == part_id))
        if row is None:
            now = time.time()
            row = QualificationRow(finger_id=finger_id, part_id=part_id, prediction=None, history=[], created=now, updated=now)
            s.add(row)
            s.flush()
        qualification_id = row.id
    return get_qualification(db, qualification_id)


def list_qualifications(db: DatabaseClient, *, finger_id: str | None = None, part_id: str | None = None) -> list[QualificationView]:
    """Every qualification, filtered by finger and/or part, most recently updated first."""
    query = select(QualificationRow).order_by(QualificationRow.updated.desc(), QualificationRow.id.desc())
    if finger_id is not None:
        query = query.where(QualificationRow.finger_id == finger_id)
    if part_id is not None:
        query = query.where(QualificationRow.part_id == part_id)
    with db.session() as s:
        found = [Qualification.model_validate(row) for row in s.scalars(query)]
    return _views(db, found)


def get_qualification(db: DatabaseClient, qualification_id: int) -> QualificationView:
    with db.session() as s:
        row = s.get(QualificationRow, qualification_id)
        if row is None:
            raise QualificationNotFoundError(qualification_id)
        found = Qualification.model_validate(row)
    return _views(db, [found])[0]


def add_session(
    db: DatabaseClient,
    qualification_id: int,
    *,
    trials: int,
    successes: int,
    kind: SessionKind = "natural",
    predicted_success: float | None = None,
    notes: str = "",
    operator: str | None = None,
    date: str | None = None,
) -> QualificationView:
    """Log a real-robot session against the pair."""
    get_qualification(db, qualification_id)
    values = {
        "qualification_id": qualification_id,
        "kind": kind,
        "trials": trials,
        "successes": successes,
        "predicted_success": predicted_success,
        "notes": notes,
        "operator": operator,
        "date": date,
    }
    _validated({**values, "id": 0, "created": 0.0})
    with db.session() as s:
        s.add(RealSessionRow(**values, created=time.time()))
        s.get(QualificationRow, qualification_id).updated = time.time()
    logger.info("Qualification %d: logged %d/%d (%s)", qualification_id, successes, trials, kind)
    return get_qualification(db, qualification_id)


def update_session(db: DatabaseClient, qualification_id: int, session_id: int, changes: dict[str, Any]) -> QualificationView:
    """Change the fields sent of one session (PATCH)."""
    unknown = set(changes) - SESSION_FIELDS
    if unknown:
        raise QualificationInputError(f"can't change {', '.join(sorted(unknown))}")
    with db.session() as s:
        row = _session_row(s, qualification_id, session_id)
        merged = _validated({**RealSession.model_validate(row).model_dump(), **changes})
        for key in changes:
            setattr(row, key, getattr(merged, key))
    return get_qualification(db, qualification_id)


def delete_session(db: DatabaseClient, qualification_id: int, session_id: int) -> QualificationView:
    with db.session() as s:
        s.delete(_session_row(s, qualification_id, session_id))
    return get_qualification(db, qualification_id)


def _session_row(s, qualification_id: int, session_id: int) -> RealSessionRow:
    row = s.get(RealSessionRow, session_id)
    if row is None or row.qualification_id != qualification_id:
        raise SessionNotFoundError(session_id)
    return row


def _validated(values: dict[str, Any]) -> RealSession:
    try:
        return RealSession.model_validate(values)
    except ValidationError as e:
        raise QualificationInputError(
            "; ".join(f"{'.'.join(map(str, err['loc'])) or 'session'}: {err['msg']}" for err in e.errors())
        ) from e


def _views(db: DatabaseClient, found: list[Qualification]) -> list[QualificationView]:
    """The qualifications with their sessions, finger and part names, and what follows from the sessions."""
    with db.session() as s:
        sessions = [
            RealSession.model_validate(row)
            for row in s.scalars(
                select(RealSessionRow).where(RealSessionRow.qualification_id.in_([q.id for q in found])).order_by(RealSessionRow.id)
            )
        ]
        fingers = {fid: (number, name) for fid, number, name in s.execute(select(FingerRow.id, FingerRow.number, FingerRow.name))}
        names = dict(s.execute(select(PartRow.id, PartRow.name).where(PartRow.id.in_({q.part_id for q in found}))).all())
    out = []
    for q in found:
        mine = [x for x in sessions if x.qualification_id == q.id]
        comparisons = compare(q.prediction, mine)
        trials = sum(x.trials for x in mine)
        number, name = fingers.get(q.finger_id, (0, "(removed)"))
        out.append(
            QualificationView(
                **q.model_dump(),
                finger_code=finger_code(number),
                finger_name=name,
                part_name=names.get(q.part_id),
                sessions=mine,
                status="validated" if mine else "simulated",
                measured_success=sum(x.successes for x in mine) / trials if trials else None,
                real_trials=trials,
                comparisons=comparisons,
                gap_flagged=any(c.gap_flagged for c in comparisons),
            )
        )
    return out
