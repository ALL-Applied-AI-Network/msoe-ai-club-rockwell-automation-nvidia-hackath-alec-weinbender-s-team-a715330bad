"""Everything the input steps collect for a generation job (the optimizer designing new fingers): enough to plan it, run
it, and duplicate it later. An evaluation job's spec is api/models/evaluation.py: EvaluationSpec."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from api.models.error_model import ErrorModel
from api.models.family import FamilyChoice
from api.models.grasp import GraspChoice
from api.models.task import Task

SimBackend = Literal["mock", "isaac"]  # the badge on every job, result and export; mock results are never predictions
MAX_POSES = 4  # the stable poses GET /api/parts/{id}/poses offers


class PoseGrasp(BaseModel):
    """One resting pose the job covers (step 2) and the grasp for it (step 5)."""

    pose: Annotated[int, Field(ge=0, strict=True)] | Literal["as_authored"]  # an index into GET /api/parts/{id}/poses
    grasp: GraspChoice


class JobSpec(BaseModel):
    kind: Literal["generation"] = "generation"  # specs stored before evaluation jobs existed have no kind: generation
    name: str | None = None  # the experiment's name; blank: "<CAD file stem>_<date>", e.g. "vial-cap_2026-10-19"
    part_id: str  # a PartRecord with a material (or measured mass)
    cell_profile_id: int  # a CellProfileVersion: the exact version confirmed in step 4
    task: Task = Task()
    # The resting poses and their grasps: `poses`, or (as every spec did before jobs covered poses) one `grasp` for the
    # part record's chosen pose. Exactly one of the two.
    grasp: GraspChoice | None = None
    poses: list[PoseGrasp] = Field(default_factory=list, max_length=MAX_POSES)
    families: list[FamilyChoice] = Field(default_factory=lambda: [FamilyChoice()], min_length=1)
    # None: the cell profile's grasp accuracy, copied in when the job is planned, so a stored job always has one
    error: ErrorModel | None = None
    budget: int | None = Field(None, ge=1)  # designs per search; None: the rule in search_plan.py
    seed: int = 0

    def with_error(self, default: ErrorModel) -> "JobSpec":
        """This spec with its error model filled in: its own, else `default` (the cell profile's grasp accuracy)."""
        return self if self.error is not None else self.model_copy(update={"error": default})

    @model_validator(mode="after")
    def _one_choice_per_family(self) -> "JobSpec":
        names = [choice.family for choice in self.families]
        if len(names) != len(set(names)):
            raise ValueError("each finger family can be ticked once")
        return self

    @model_validator(mode="after")
    def _grasp_or_poses(self) -> "JobSpec":
        if (self.grasp is None) == (not self.poses):
            raise ValueError("give the resting poses with their grasps (poses), or one grasp for the part's chosen pose")
        chosen = [p.pose for p in self.poses]
        if len(chosen) != len(set(chosen)):
            raise ValueError("each resting pose can be chosen once")
        if "as_authored" in chosen and len(chosen) > 1:
            raise ValueError('"as in the CAD file" has no likelihood to weigh it by: it can only be the one pose')
        return self
