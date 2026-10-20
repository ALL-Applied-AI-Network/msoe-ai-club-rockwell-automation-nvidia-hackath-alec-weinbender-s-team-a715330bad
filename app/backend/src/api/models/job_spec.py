"""Everything the input steps collect: enough to plan a job, run it, and duplicate it later."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from api.models.error_model import ErrorModel
from api.models.family import FamilyChoice
from api.models.grasp import GraspChoice
from api.models.task import Task

SimBackend = Literal["mock", "isaac"]  # the badge on every job, result and export; mock results are never predictions


class JobSpec(BaseModel):
    name: str | None = None  # the experiment's name; blank: "<CAD file stem>_<date>", e.g. "vial-cap_2026-10-19"
    part_id: str  # a PartRecord with a material (or measured mass) and a resting pose
    cell_profile_id: int  # a CellProfileVersion: the exact version confirmed in step 4
    task: Task = Task()
    grasp: GraspChoice
    families: list[FamilyChoice] = Field(default_factory=lambda: [FamilyChoice()], min_length=1)
    error: ErrorModel = ErrorModel()
    budget: int | None = Field(None, ge=1)  # designs per search; None: the rule in search_plan.py
    seed: int = 0

    @model_validator(mode="after")
    def _one_choice_per_family(self) -> "JobSpec":
        names = [choice.family for choice in self.families]
        if len(names) != len(set(names)):
            raise ValueError("each finger family can be ticked once")
        return self
