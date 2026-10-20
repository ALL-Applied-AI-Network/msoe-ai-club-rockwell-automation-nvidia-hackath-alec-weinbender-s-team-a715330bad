"""Digital vs physical: how the sim's predictions compare with what the real robot measured, on exactly the same
offsets (the test plan's), so any gap is sim-to-real error and not a different test. Built by the results tracker
(services/physical_trials.py) and shown on the results page and the job card.

What counts as a success on the robot follows the job's task: held for pick and drop; held with in_tolerance "yes" for
place and insert. A held place / insert trial whose in_tolerance was left blank is incomplete: it's left out of every rate
and comparison until it's filled in, rather than guessed either way. Skipped trials are left out too, and so are extra
trials, which have no prediction.
"""

import math
from typing import Literal

from pydantic import BaseModel

from api.models.job_spec import SimBackend

PhysicalBadge = Literal["none", "in_progress", "validated"]  # none yet: nothing logged; validated: every planned trial logged
# sim_only: the sim said success, the robot failed; real_only: the reverse; mixed: the robot's repeats split evenly
MismatchStatus = Literal["agreed", "sim_only", "real_only", "mixed", "pending"]
Z_95 = 1.959963984540054  # the standard normal's 97.5th percentile


class DesignValidation(BaseModel):
    """One tested design: predicted vs measured success on its planned trials, across every test plan of the job."""

    design_label: str
    finger_ids: list[str]  # its printed fingers (engraved IDs); none for STOCK
    planned: int  # planned trials
    logged: int  # planned trials with an outcome (held, missed or skipped)
    skipped: int
    incomplete: int  # held on place / insert with in_tolerance blank
    extras: int  # extra trials logged off the plan
    n: int  # the trials both rates are over: logged, not skipped, not incomplete
    predicted_success: float | None  # the sim's success rate on those trials (the ones it has predicted)
    measured_success: float | None
    wilson_low: float | None  # 95% Wilson interval on the measured rate
    wilson_high: float | None
    offsets: int  # unique point-wise offsets planned
    offsets_compared: int  # point-wise offsets with a prediction and at least one counted trial
    offsets_agreed: int  # of those, where the robot's majority over the repeats matched the sim
    summary: str  # e.g. "sim matched reality on 22 of 25 offsets"


class MismatchPoint(BaseModel):
    """One planned offset of one design on the held map (repeats and plans pooled)."""

    design_label: str
    kind: Literal["pointwise", "random"]
    offset_x_mm: float
    offset_y_mm: float
    yaw_deg: float
    predicted: bool | None  # the sim's task success there; None until predicted
    measured_rate: float | None  # over its counted trials
    repeats: int  # counted trials
    status: MismatchStatus


class CurvePoint(BaseModel):
    """Measured success on the random (error-model) trials, to overlay on the success-vs-error curve at the job's sigma."""

    design_label: str
    sigma_mm: float
    measured_success: float
    wilson_low: float
    wilson_high: float
    n: int
    predicted_success: float | None  # the sim's rate on the same random offsets


class Validation(BaseModel):
    badge: PhysicalBadge
    sim_backend: SimBackend | None = None  # what predicted: a mock's predictions are not results
    designs: list[DesignValidation] = []
    mismatches: list[MismatchPoint] = []
    curve_points: list[CurvePoint] = []


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval for a success rate: unlike p +- z*sqrt(p(1-p)/n), it stays inside [0, 1] and isn't zero
    wide at 0 or n successes, which small physical samples hit all the time."""
    if n <= 0:
        raise ValueError("a Wilson interval needs at least one trial")
    p, z2 = successes / n, z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)
