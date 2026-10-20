from typing import Any

from pydantic import BaseModel, ConfigDict

from sim_server.models.finger import FingerDesign
from sim_server.models.pose import PartPose


class GraspPlanError(ValueError):
    """The twin's IK can't follow a design's grasp motion (e.g. an unreachable tip height): a problem with the request,
    which the router answers with 422. Raised by robot/motion.py; defined here so every layer can catch it without
    importing numpy."""


class GraspSettings(BaseModel):
    """What the robot commands for a design: fingertip height above the work surface, and the per-jaw opening it closes
    to (0 closed .. 6 mm open). Metres."""

    model_config = ConfigDict(frozen=True)

    tip_height: float
    jaw_close: float


class EnvGrasp(BaseModel):
    """One environment's grasp within a chunk: the design, the motion planned for it at the nominal pose (shared by every
    copy of the design), and the part's true pose (nominal + offset, base frame). plan is a robot/motion.GraspPlan,
    typed loosely so models stay free of numpy."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    design: FingerDesign
    plan: Any
    pose: PartPose
