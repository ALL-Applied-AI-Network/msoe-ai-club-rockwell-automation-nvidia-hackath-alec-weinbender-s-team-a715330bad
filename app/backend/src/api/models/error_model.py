"""The camera-error model (input step 7): how far the part's true position may be from where the robot thinks it is.

dx and dy are independent normals with sigma_mm (so the radial error is Rayleigh), yaw a normal with sigma_deg, all in the
gripper's frame at the grasp. A bias shifts the centre of the position error: calibration that's consistently off one
way, by bias_mm toward bias_direction_deg (0 = along the closing direction, toward +x; 90 = toward +y).

"Design for a range" scores each design by its mean expected success over several sigmas spread across sigma_range_mm.
None of this needs extra simulation: the outcomes on the fixed offset grid re-weight to any error model
(api/models/offset_grid.py).
"""

import math
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

PresetName = Literal["twin", "calibrated", "typical", "cheap", "custom"]
RANGE_SIGMAS = 6  # sigmas a range is averaged over, evenly spread from its low to its high end
CURVE_SIGMAS_MM = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0)  # where success-vs-error curves are reported


@dataclass(frozen=True)
class Preset:
    label: str
    sigma_mm: float
    sigma_deg: float
    placeholder: bool  # True until replaced by error measured on the real cell
    note: str


PRESETS: dict[str, Preset] = {
    "twin": Preset("Twin perception", 0.19, 0.5, False, "as measured in the organizers' twin (the yaw is a placeholder)"),
    "calibrated": Preset("Well calibrated", 1.0, 3.0, True, "placeholder until measured on the cell"),
    "typical": Preset("Typical", 3.0, 8.0, True, "the current default; placeholder until measured on the cell"),
    "cheap": Preset("Cheap camera or clear parts", 5.0, 12.0, True, "placeholder until measured on the cell"),
}


class ErrorModel(BaseModel):
    preset: PresetName = "typical"  # a label: the numbers below are what count
    sigma_mm: float = Field(3.0, ge=0)  # the target sigma, per axis
    sigma_range_mm: tuple[float, float] | None = None  # design for this range instead of one sigma
    sigma_deg: float = Field(8.0, ge=0)  # yaw; used for boxes, lying cylinders and mesh parts
    bias_mm: float = Field(0.0, ge=0)
    bias_direction_deg: float = 0.0

    @model_validator(mode="after")
    def _range(self) -> "ErrorModel":
        if self.sigma_range_mm is not None:
            lo, hi = self.sigma_range_mm
            if lo < 0 or hi < lo:
                raise ValueError("sigma_range_mm needs 0 <= low <= high")
        return self

    @classmethod
    def from_preset(cls, name: str) -> "ErrorModel":
        preset = PRESETS[name]
        return cls(preset=name, sigma_mm=preset.sigma_mm, sigma_deg=preset.sigma_deg)

    @property
    def bias_xy(self) -> tuple[float, float]:
        a = math.radians(self.bias_direction_deg)
        return self.bias_mm * math.cos(a), self.bias_mm * math.sin(a)

    @property
    def sigmas_mm(self) -> list[float]:
        """The sigmas a design is scored at: the target alone, or RANGE_SIGMAS spread across the range."""
        if self.sigma_range_mm is None:
            return [self.sigma_mm]
        lo, hi = self.sigma_range_mm
        if hi == lo:
            return [lo]
        return [lo + (hi - lo) * i / (RANGE_SIGMAS - 1) for i in range(RANGE_SIGMAS)]

    def at_sigma(self, sigma_mm: float) -> "ErrorModel":
        """The same model (bias, yaw) at one position sigma: a point of a success-vs-error curve."""
        return self.model_copy(update={"sigma_mm": sigma_mm, "sigma_range_mm": None})
