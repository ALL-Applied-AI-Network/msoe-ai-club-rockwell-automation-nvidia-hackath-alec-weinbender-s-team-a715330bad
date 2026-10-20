"""The task (input step 3): what happens after the pick, and so what counts as a successful grasp. It changes which finger
wins, not how the optimizer searches, and since the raw outcomes are stored, any task or tolerance re-scores without
simulating again.

| Task            | Succeeds at an offset when                                                        |
| pick and drop   | held (and still held after the transport move, if there is one)                   |
| pick and place  | that, and the part's in-hand offset is within the placement tolerance             |
| pick and insert | that, and its tilt is within the tilt tolerance too                               |

In-hand offset is the 3-D distance between where the part's centre sits in the hand after the lift and where a centred
part would sit (api/models/outcome.py). A held grasp with no reported in-hand pose fails place and insert: there is
nothing to check the tolerance against.
"""

import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from api.models.outcome import InHand, Outcomes

TaskKind = Literal["drop", "place", "insert"]
Transport = Literal["slow", "normal", "fast"]
TASK_LABELS = {"drop": "Pick and drop", "place": "Pick and place", "insert": "Pick and insert"}


class Task(BaseModel):
    kind: TaskKind = "drop"
    offset_tolerance_mm: float | None = Field(None, gt=0)  # place and insert
    tilt_tolerance_deg: float | None = Field(None, gt=0)  # insert
    transport: Transport | None = None  # a quick move after the lift, to test grip security

    @model_validator(mode="after")
    def _tolerances(self) -> "Task":
        if self.kind in ("place", "insert") and self.offset_tolerance_mm is None:
            raise ValueError(f"pick and {self.kind} needs a placement tolerance (offset_tolerance_mm)")
        if self.kind == "insert" and self.tilt_tolerance_deg is None:
            raise ValueError("pick and insert needs a tilt tolerance (tilt_tolerance_deg)")
        return self

    def success(self, outcomes: Outcomes) -> list[bool]:
        """Per offset: whether the grasp succeeded at this task."""
        after = outcomes.held_after_transport if self.transport else None
        return [
            held and (after is None or after[i]) and self.within_tolerance(outcomes.in_hand[i]) is not False
            for i, held in enumerate(outcomes.held)
        ]

    def within_tolerance(self, in_hand: InHand | None) -> bool | None:
        """Whether a held part sits within the task's tolerances; None when the task has none (pick and drop)."""
        if self.kind == "drop":
            return None
        if in_hand is None:
            return False
        if offset_mm(in_hand) > self.offset_tolerance_mm:
            return False
        return self.kind != "insert" or in_hand[3] <= self.tilt_tolerance_deg


def offset_mm(in_hand: InHand) -> float:
    """How far the part's centre sits from where a centred part would, in mm."""
    dx, dy, dz, _, _ = in_hand
    return math.sqrt(dx * dx + dy * dy + dz * dz)
