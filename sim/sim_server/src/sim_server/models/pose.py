from pydantic import BaseModel, ConfigDict


class PartPose(BaseModel):
    """Where a part rests, in the robot base frame (see robot/poses.py)."""

    model_config = ConfigDict(frozen=True)

    position: tuple[float, float, float]  # the part's centre, metres
    yaw_deg: float  # about +Z; 0 means the part's x axis is base +X


class BodyPose(BaseModel):
    """Where a body is, as measured by the simulator: its origin in its environment's robot base frame (metres) and its
    full orientation as a unit quaternion (w, x, y, z), Isaac's scalar-first order."""

    model_config = ConfigDict(frozen=True)

    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]


class InHandPose(BaseModel):
    """The part in the hand at the end of the lift, relative to the commanded gripper frame G and to where a perfectly
    centred part would sit (robot/poses.in_hand_pose). dx along the closing direction (toward JawL), dy across it, dz
    up, in metres; tilt is the angle between the part's z axis and G's, yaw the turn of its x axis about G's z. For a
    cylinder both follow its own axis, so a roll about that axis reads zero."""

    model_config = ConfigDict(frozen=True)

    dx: float
    dy: float
    dz: float
    tilt_deg: float
    yaw_deg: float
