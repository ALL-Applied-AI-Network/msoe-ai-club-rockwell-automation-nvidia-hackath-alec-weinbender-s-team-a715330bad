from pydantic import BaseModel, ConfigDict

from sim_server.models.finger import FingerDesign
from sim_server.models.offset import Offset
from sim_server.models.part import Part


class GraspBatch(BaseModel):
    """One request in the twin's units: every design is tried at every offset."""

    model_config = ConfigDict(frozen=True)

    part: Part
    designs: tuple[FingerDesign, ...]
    offsets: tuple[Offset, ...]
