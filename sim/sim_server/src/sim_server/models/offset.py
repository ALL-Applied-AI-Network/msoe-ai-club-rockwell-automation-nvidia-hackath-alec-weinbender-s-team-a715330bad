from pydantic import BaseModel, ConfigDict


class Offset(BaseModel):
    """Camera error: the part's true pose relative to where the robot thinks it is, in the gripper's frame at the
    grasp. dx along the closing direction (+ toward JawL), dy across it (G's +y), yaw about the vertical."""

    model_config = ConfigDict(frozen=True)

    dx: float  # metres
    dy: float  # metres
    yaw_deg: float
