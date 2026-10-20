from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from sim_server.models.piece import Piece

CylinderAxis = Literal["z", "y", "x"]


class Part(BaseModel):
    """The part, in metres and kilograms, in its own nominal frame: x along the jaws' closing direction (toward JawL), y
    across it, z up, origin at mid-height above the grasp centre. size is its extent along those axes.

    - A cylinder's axis is "z" when it stands on an end, "y" when it lies across the jaws, "x" when it lies along them
      (the jaws grip its end faces).
    - A mesh is a union of convex pieces in that frame (services/batches.py recentres the request's pieces, which sit on
      the table, to mid-height), so the nominal pose and the held check treat it like a primitive.
    - friction is the part's (static, dynamic) physics material; None keeps the twin's part material (0.9 / 0.8).

    Two parts that differ in anything, friction included, need a stage edit between them."""

    model_config = ConfigDict(frozen=True)

    shape: Literal["cylinder", "box", "mesh"]
    size: tuple[float, float, float]
    mass: float
    cylinder_axis: CylinderAxis | None = None
    pieces: tuple[Piece, ...] | None = None
    friction: tuple[float, float] | None = None

    @model_validator(mode="after")
    def _shape_fields(self) -> "Part":
        if (self.shape == "cylinder") != (self.cylinder_axis is not None):
            raise ValueError("a cylinder, and only a cylinder, has a cylinder_axis")
        if (self.shape == "mesh") != bool(self.pieces):
            raise ValueError("a mesh, and only a mesh, has pieces")
        return self

    @property
    def width(self) -> float:
        """Extent along the jaws' closing direction at the nominal pose."""
        return self.size[0]

    @property
    def height(self) -> float:
        return self.size[2]

    @property
    def length(self) -> float:
        """A cylinder's extent along its axis."""
        return self.size["xyz".index(self.cylinder_axis)]

    @property
    def diameter(self) -> float:
        """A cylinder's diameter: its extent along any axis but its own."""
        return self.size[0] if self.cylinder_axis == "z" else self.size[2]
