from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict

ReviewStatus = Literal["approved", "rejected", "pending"]
REVIEW_STATUSES: tuple[str, ...] = get_args(ReviewStatus)


class Review(BaseModel):
    """The safety gate: no printed finger goes on the real arm until a named reviewer approves it."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    status: ReviewStatus
    reviewer: str
    notes: str
    created: float
