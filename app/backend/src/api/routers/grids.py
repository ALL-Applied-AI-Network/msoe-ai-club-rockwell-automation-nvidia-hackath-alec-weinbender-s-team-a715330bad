"""The offset grid and its weights under an error model (input step 7)."""

from fastapi import APIRouter
from pydantic import BaseModel

from api.models.error_model import ErrorModel
from api.models.offset_grid import GridPreview
from api.models.part import Part
from api.services import grids

router = APIRouter(prefix="/api/grids", tags=["grids"])


class GridRequest(BaseModel):
    part: Part  # as the gripper meets it: decides whether yaw is tested
    parts: list[Part] = []  # the part in every resting pose a job covers (the plan's poses), when there are several
    error: ErrorModel = ErrorModel()
    final: bool = False  # the final test's dense grid instead of the search grid


class GridResponse(GridPreview):
    pass


@router.post("")
def preview_grid(request: GridRequest) -> GridResponse:
    """Points with their weights, the 1σ and 2σ circles around the bias, the outer ring, the yaw layers and warnings.
    Cheap enough to call on every slider move."""
    return GridResponse.model_validate(grids.grid_preview(request.part, request.error, request.final, request.parts).model_dump())
