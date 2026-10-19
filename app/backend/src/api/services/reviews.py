"""The safety review gate. Plant rule: no printed finger goes on the real arm until a named reviewer approves it."""

import logging

from api.clients.database import DatabaseClient
from api.db.tables import ReviewRow
from api.models.review import REVIEW_STATUSES, Review

logger = logging.getLogger(__name__)


class ReviewError(ValueError):
    """The review was rejected; the message says why."""


def set_review(db: DatabaseClient, job_id: str, *, status: str, reviewer: str, notes: str) -> None:
    """Record the job's review, replacing any earlier one."""
    if status not in REVIEW_STATUSES:
        raise ReviewError("bad status")
    if status == "approved" and not reviewer.strip():
        raise ReviewError("reviewer name required")
    with db.session() as s:
        s.merge(ReviewRow(job_id=job_id, status=status, reviewer=reviewer, notes=notes))
    logger.info("Job %s: review %s by %s", job_id, status, reviewer or "(unnamed)")


def get_review(db: DatabaseClient, job_id: str) -> Review | None:
    with db.session() as s:
        row = s.get(ReviewRow, job_id)
        return Review.model_validate(row) if row else None
