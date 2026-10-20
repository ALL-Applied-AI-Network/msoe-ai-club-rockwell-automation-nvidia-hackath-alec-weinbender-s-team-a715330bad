from pydantic import BaseModel, ConfigDict


class PartPose(BaseModel):
    """Where a part rests, in the robot base frame (see robot/poses.py)."""

    model_config = ConfigDict(frozen=True)

    position: tuple[float, float, float]  # the part's centre, metres
    yaw_deg: float  # about +Z; 0 means the part's x axis is base +X
