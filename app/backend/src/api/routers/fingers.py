"""Finger previews for the design-space sliders (input step 6)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from api.dependencies import DbDep
from api.models.design import Design
from api.models.family import FamilyChoice
from api.models.finger import Finger
from api.models.part import Part
from api.models.search_space import ParamSummary
from api.services import fingers
from api.services.cell_profiles import CellProfileNotFoundError

router = APIRouter(prefix="/api/fingers", tags=["fingers"])


class FingerPreviewRequest(BaseModel):
    part: Part  # as the gripper meets it (posed and turned to the grasp axis)
    others: list[Part] = []  # the job's other resting poses (JobPlan.poses after the first): they bound the slack too
    cell_profile_id: int
    choice: FamilyChoice = FamilyChoice()
    clearance_mm: float | None = Field(None, ge=0)  # the part record's clearance on the table, if set
    grip_height_mm: float | None = Field(None, gt=0)  # the grasp's grip height, if locked in step 5
    vary: str | None = None  # a free parameter: preview its low ("min") and high ("max") ends, the others in the middle
    designs: list[Design] | None = Field(None, min_length=1, max_length=8)  # or these designs, labelled by index

    @model_validator(mode="after")
    def _one_kind(self) -> "FingerPreviewRequest":
        if self.vary is not None and self.designs is not None:
            raise ValueError("give vary or designs, not both")
        return self


class DesignPreviewResponse(BaseModel):
    label: str
    design: Design
    finger: Finger | None  # pieces, grasp settings and closed gap; None if it couldn't be built
    problems: list[str]


class FingerPreviewResponse(BaseModel):
    designs: list[DesignPreviewResponse]
    free: list[str]
    params: list[ParamSummary]


@router.post("/preview")
def preview_fingers(request: FingerPreviewRequest, db: DbDep) -> FingerPreviewResponse:
    """The fingers for a family choice: the two ends of one parameter, given designs, or the middle design."""
    try:
        preview = fingers.preview_fingers(
            db,
            request.part,
            request.cell_profile_id,
            request.choice,
            clearance_mm=request.clearance_mm,
            grip_height_mm=request.grip_height_mm,
            vary=request.vary,
            designs=request.designs,
            others=request.others,
        )
    except CellProfileNotFoundError:
        raise HTTPException(404, f"no cell profile {request.cell_profile_id}") from None
    except fingers.PreviewError as e:
        raise HTTPException(422, str(e)) from None
    return FingerPreviewResponse(
        designs=[DesignPreviewResponse(label=d.label, design=d.design, finger=d.finger, problems=d.problems) for d in preview.designs],
        free=preview.free,
        params=preview.params,
    )
