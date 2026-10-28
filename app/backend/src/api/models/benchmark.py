"""Offline benchmark inputs and observations; no production job schema changes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.models.design import Design
from api.models.outcome import Outcomes


class BenchmarkConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: Literal["cube", "cube16", "screw"] = "cube"
    budget: int = Field(32, ge=1)
    seeds: list[int] = Field(default_factory=lambda: [0, 1, 2], min_length=1)
    reference_grasps_per_s: float = Field(5.0, gt=0)
    selection_repeats: int = Field(1, ge=1)
    pilot: bool = False

    @field_validator("seeds")
    @classmethod
    def valid_seeds(cls, seeds: list[int]) -> list[int]:
        if len(set(seeds)) != len(seeds) or any(seed < 0 or seed >= 2**31 for seed in seeds):
            raise ValueError("seeds must be unique integers between 0 and 2**31-1")
        return seeds


class Observation(BaseModel):
    seed: int
    method: str
    phase: str
    number: int
    batch: int
    design: Design
    success_rate: float
    capture_radius_mm: float | None
    outcomes: Outcomes
    grasps: int
    measured_grasps: int | None = None
    cumulative_grasps: int = 0
    proposal_s: float
    geometry_s: float
    simulator_s: float
    source: str
    fallback_reason: str | None = None
    rejections: list[str]
    parameter_hash: str
    geometry_hash: str | None
    duplicate_parameters: bool = False
    duplicate_geometry: bool = False

    @property
    def params(self):
        return self.design.params
