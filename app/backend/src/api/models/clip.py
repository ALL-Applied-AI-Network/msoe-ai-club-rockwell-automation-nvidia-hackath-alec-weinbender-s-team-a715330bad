"""Isaac Sim clips: one grasp of a finished experiment's final design, filmed by the sim server at one grid point, so the
results page can show the real twin closing on the part (services/clips.py)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

ClipStatus = Literal["queued", "recording", "ready", "failed"]
ACTIVE_CLIP_STATUSES: tuple[ClipStatus, ...] = ("queued", "recording")  # a worker has, or is about to have, the clip
# closeup: the fingers and the part at the grasp site, across the jaws' closing direction. side: the cell's side camera.
ClipView = Literal["closeup", "side"]
CLIP_VIEWS: tuple[ClipView, ...] = ("closeup", "side")
ClipOutcome = Literal["held", "missed"]


class ClipOffset(BaseModel):
    """The camera error the grasp is filmed at, as the results' grid points give it (mm, degrees)."""

    dx: Annotated[float, Field(ge=-50, le=50)]  # along the jaws' closing direction, + toward JawL
    dy: Annotated[float, Field(ge=-50, le=50)]
    yaw_deg: Annotated[float, Field(ge=-180, le=180)] = 0.0


class ClipRequest(BaseModel):
    design: str = Field(min_length=1, max_length=16)  # a final design's label, any case: D1, D2, ..., STOCK, IMP
    offset: ClipOffset


class Clip(BaseModel):
    id: int
    job_id: str
    design: str  # D1, ..., STOCK, IMP
    offset: ClipOffset
    status: ClipStatus
    views: list[ClipView]  # the videos it has (or will have)
    outcome: ClipOutcome | None  # this recording's own outcome, once ready
    result: ClipOutcome | None  # the job's stored outcome at this offset, when it's a point of the final grid
    matches_result: bool | None  # outcome == result; False now and then near the capture edge, where grasps aren't repeatable
    duration_s: float | None
    error: str | None  # why it failed
    created: float
    recorded: float | None
