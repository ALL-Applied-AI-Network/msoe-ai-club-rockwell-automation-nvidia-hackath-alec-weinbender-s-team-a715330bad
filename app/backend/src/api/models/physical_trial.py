"""One grasp attempt on the real arm, logged after a supervised test: against a planned trial (matched by trial_id) or as
an extra trial with its design and offset filled in. Logging the same trial again overwrites it and keeps the old value
in history."""

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict

from api.models.test_plan import PlannedTrialKind

TrialOutcome = Literal["held", "missed", "skipped"]
TRIAL_OUTCOMES: tuple[str, ...] = get_args(TrialOutcome)
LOGGED_FIELDS = ("outcome", "in_tolerance", "finger_id", "notes", "video_link", "operator", "timestamp")  # what a re-log overwrites


class PhysicalTrial(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    job_id: str
    plan_id: int | None = None  # None for an extra trial outside any plan
    trial_id: str
    design_label: str
    finger_id: str | None = None
    kind: PlannedTrialKind
    offset_x_mm: float
    offset_y_mm: float
    yaw_deg: float
    repeat: int = 1
    outcome: TrialOutcome
    in_tolerance: bool | None = None  # place and insert only
    notes: str = ""
    video_link: str | None = None
    operator: str | None = None
    timestamp: str | None = None  # ISO; filled in on upload if blank
    history: list[dict[str, Any]] = []  # earlier values of this trial (LOGGED_FIELDS plus "replaced", when), oldest first
    created: float


class RowError(BaseModel):
    """A row of an upload (or a quick log) that wasn't applied, and why."""

    row: int  # as the spreadsheet numbers it (the header is row 1); 0 for a quick log
    trial_id: str | None = None
    reason: str


class LogReport(BaseModel):
    """What an upload did. Valid rows are applied even when others have errors."""

    accepted: int  # rows logged: new outcomes, changed ones (the old value goes to history) and new extra trials
    extras: int  # of those, new extra trials
    extra_trial_ids: list[str] = []  # the IDs they were given
    unchanged: int  # rows identical to what was already logged (no history entry)
    pending: int  # the plan's planned trials still without an outcome, after this upload
    errors: list[RowError] = []
