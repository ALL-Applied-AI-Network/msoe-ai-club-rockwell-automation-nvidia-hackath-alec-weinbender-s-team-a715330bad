from pydantic import BaseModel, ConfigDict

from sim_server.models.finger import FingerDesign
from sim_server.models.grasp import Transport
from sim_server.models.offset import Offset
from sim_server.models.part import Part


class GraspBatch(BaseModel):
    """One request in the twin's units: every design is tried at every offset.

    grip_force is the per-jaw force limit on the jaw drive, in newtons; None keeps the twin's drive (scene_config
    JAW_MAX_FORCE, 180 N). transport adds a move after the lift (robot/motion.py); None ends the grasp at the lift."""

    model_config = ConfigDict(frozen=True)

    part: Part
    designs: tuple[FingerDesign, ...]
    offsets: tuple[Offset, ...]
    grip_force: float | None = None
    transport: Transport | None = None
