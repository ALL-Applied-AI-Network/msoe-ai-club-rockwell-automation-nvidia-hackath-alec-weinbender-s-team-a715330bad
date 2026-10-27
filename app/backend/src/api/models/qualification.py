"""A qualification: one library finger on one part, the sim's prediction for that pair and what the real robot measured.

There is one per (finger, part). Every finished evaluation job that tries the finger on the part updates its prediction
(the earlier ones go to history). The robotics engineer logs real-robot sessions against it as counts: trials and
successes. The pair is "validated" once a session is logged, and its gap is flagged when the sim's prediction falls
outside the 95% Wilson interval of what the robot measured.

Two kinds of session, compared with different predictions:
- natural: the cell running as it does day to day, with its own grasp error. Pooled, and compared with the prediction
  (the expected success at the cell's grasp accuracy).
- commanded: deliberate offsets, as our runs on the organizers' platform command them (cell_policy/). Each is compared
  with its own predicted_success, the sim's rate at exactly those offsets (a generation job's test plan predicts it),
  since the accuracy-weighted prediction is for different grasps.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.models.error_model import ErrorModel
from api.models.grasp import GraspChoice
from api.models.job_spec import SimBackend
from api.models.task import Task
from api.models.validation import wilson_interval

SessionKind = Literal["natural", "commanded"]
QualificationStatus = Literal["simulated", "validated"]


class Prediction(BaseModel):
    """What one evaluation job predicted for the pair."""

    job_id: str
    experiment_id: str
    success: float  # at its best grasp per pose, weighted over the poses
    stage: Literal["search", "final"]
    n_grasps: int
    error: ErrorModel  # the grasp accuracy it was scored at
    task: Task
    grasps: list[GraspChoice]  # its best grasp in each pose it grips, primary pose first
    sim_backend: SimBackend  # a mock's prediction is geometry only, never a result
    created: float


class RealSession(BaseModel):
    """One sitting at the real robot: how many grasps were tried and how many succeeded."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    qualification_id: int
    kind: SessionKind = "natural"
    trials: int = Field(ge=1)
    successes: int = Field(ge=0)
    predicted_success: float | None = Field(None, ge=0, le=1)  # commanded: the sim's rate at the commanded offsets
    notes: str = ""
    operator: str | None = None
    date: str | None = None  # ISO
    created: float

    @model_validator(mode="after")
    def _counts(self) -> "RealSession":
        if self.successes > self.trials:
            raise ValueError("more successes than trials")
        return self


class Comparison(BaseModel):
    """Sim against robot for a group of sessions: the natural ones pooled, or one commanded session."""

    kind: SessionKind
    session_ids: list[int]
    trials: int
    successes: int
    measured_success: float
    wilson_low: float
    wilson_high: float
    predicted_success: float | None  # None: nothing to compare with yet
    gap_flagged: bool  # the prediction lies outside the Wilson interval


class Qualification(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    finger_id: str
    part_id: str
    prediction: Prediction | None = None  # the latest
    history: list[Prediction] = []  # earlier predictions, oldest first
    created: float
    updated: float


class QualificationView(Qualification):
    """A qualification with its sessions and what follows from them."""

    finger_code: str
    finger_name: str
    part_name: str | None
    sessions: list[RealSession]
    status: QualificationStatus
    measured_success: float | None  # every session pooled
    real_trials: int
    comparisons: list[Comparison]
    gap_flagged: bool  # any comparison's


def compare(prediction: Prediction | None, sessions: list[RealSession]) -> list[Comparison]:
    """The natural sessions pooled against the prediction, then each commanded session against its own prediction."""
    out = []
    natural = [s for s in sessions if s.kind == "natural"]
    if natural:
        out.append(_comparison("natural", natural, prediction.success if prediction is not None else None))
    out += [_comparison("commanded", [s], s.predicted_success) for s in sessions if s.kind == "commanded"]
    return out


def _comparison(kind: SessionKind, sessions: list[RealSession], predicted: float | None) -> Comparison:
    trials, successes = sum(s.trials for s in sessions), sum(s.successes for s in sessions)
    low, high = wilson_interval(successes, trials)
    return Comparison(
        kind=kind,
        session_ids=[s.id for s in sessions],
        trials=trials,
        successes=successes,
        measured_success=successes / trials,
        wilson_low=low,
        wilson_high=high,
        predicted_success=predicted,
        gap_flagged=predicted is not None and not low <= predicted <= high,
    )
