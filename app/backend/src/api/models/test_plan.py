"""A physical test plan: the exact offsets to command on the real robot for each printed design, so the sim's prediction
and the robot's measurement are made on the same offsets and any gap is sim-to-real error, not a different test.

Per design: point-wise offsets (the centre; +-dx and +-dy at 1, 2, 3, 4 and 6 mm; the four diagonals at 3 mm along both
axes: 25) repeated 3 times, plus about 30 offsets drawn (seeded) from the job's error model. The sim predicts every row
before anyone touches the robot. Trial IDs (T0001, ...) are unique within the experiment, across all its plans and its
extra trials.
"""

import re
from typing import ClassVar, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict

from api.models.error_model import ErrorModel

PlannedTrialKind = Literal["pointwise", "random", "extra"]  # extra: added on a spreadsheet upload, not planned
PredictionStatus = Literal["pending", "running", "done", "failed"]

POINTWISE_DISTANCES_MM = (1.0, 2.0, 3.0, 4.0, 6.0)  # along +-x and +-y
DIAGONAL_MM = 3.0  # the diagonals sit at (+-3, +-3): 3 mm along both axes, easy to type into the robot
POINTWISE_REPEATS = 3
RANDOM_PER_DESIGN = 30
OFFSET_DECIMALS = 2  # random offsets are rounded to 0.01 mm / 0.01 deg, so what's stored is what's commanded and simulated


class PlannedTrial(BaseModel):
    trial_id: str
    design_label: str  # D1, ..., STOCK, IMP
    finger_id: str | None = None  # the engraved ID of the printed finger used, once known
    kind: PlannedTrialKind
    offset_x_mm: float  # the offset to command on the robot: x along the jaws' closing direction
    offset_y_mm: float
    yaw_deg: float
    repeat: int  # 1, 2, 3 for repeated point-wise offsets; 1 otherwise
    predicted: bool | None = None  # the sim's outcome (held, and in tolerance for place / insert); None until predicted
    predicted_in_tolerance: bool | None = None  # place and insert only

    @property
    def offset(self) -> tuple[float, float, float]:
        return offset_key(self.offset_x_mm, self.offset_y_mm, self.yaw_deg)


class TestPlan(BaseModel):
    __test__: ClassVar[bool] = False  # not a pytest class

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    job_id: str
    created: float
    seed: int
    designs: list[str]  # design labels
    rows: list[PlannedTrial]
    prediction_status: PredictionStatus = "pending"
    prediction_error: str | None = None


def offset_key(x_mm: float, y_mm: float, yaw_deg: float) -> tuple[float, float, float]:
    """An offset rounded far below anything a robot resolves, so the same offset from two rows (or plans) compares equal."""
    return round(float(x_mm), 6) + 0.0, round(float(y_mm), 6) + 0.0, round(float(yaw_deg), 6) + 0.0  # + 0.0: no -0.0


def pointwise_offsets() -> list[tuple[float, float]]:
    """The 25 point-wise offsets (x, y) in mm, at yaw 0: the centre, then +x, -x, +y, -y at each distance, then the four
    diagonals."""
    out = [(0.0, 0.0)]
    for d in POINTWISE_DISTANCES_MM:
        out += [(d, 0.0), (-d, 0.0), (0.0, d), (0.0, -d)]
    d = DIAGONAL_MM
    return out + [(d, d), (-d, d), (-d, -d), (d, -d)]


def random_offsets(error: ErrorModel, n: int, rng: np.random.Generator, *, yaw: bool) -> list[tuple[float, float, float]]:
    """n offsets (x, y, yaw) drawn from the error model at its target sigma: x and y each ~ N(bias, sigma_mm), yaw ~
    N(0, sigma_deg), or 0 when yaw is False (a part round from above, whose yaw doesn't show)."""
    bias_x, bias_y = error.bias_xy
    xy = rng.normal(loc=(bias_x, bias_y), scale=error.sigma_mm, size=(n, 2))
    yaws = rng.normal(0.0, error.sigma_deg, size=n) if yaw else np.zeros(n)
    return [
        (round(float(x), OFFSET_DECIMALS) + 0.0, round(float(y), OFFSET_DECIMALS) + 0.0, round(float(a), OFFSET_DECIMALS) + 0.0)
        for (x, y), a in zip(xy, yaws, strict=True)
    ]


def trial_id(number: int) -> str:
    return f"T{number:04d}"


def trial_number(value: str) -> int | None:
    """T0042 -> 42; None if it isn't a trial ID. Lenient about case, spaces and zero padding (t42), since people type them."""
    match = re.fullmatch(r"\s*[Tt]\s*0*(\d+)\s*", value or "")
    return int(match.group(1)) if match else None
