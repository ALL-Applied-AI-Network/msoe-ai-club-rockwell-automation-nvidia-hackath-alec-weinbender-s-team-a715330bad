from typing import Literal

from pydantic import BaseModel, Field, model_validator

from api.models.piece import Piece, pieces_bounds

CylinderAxis = Literal["z", "y", "x"]


class Part(BaseModel):
    """The part as the gripper meets it: in its resting pose, turned so the jaws close along +x, in the grasp frame
    (origin on the table under the grasp centre, z up). Millimetres and grams; the sim server converts. This is what
    the fingers, the mock and the sim see; the uploaded part it comes from is a PartRecord (part_record.py).

    A cylinder's axis is "z" when it stands on an end, "y" when it lies across the jaws, "x" when it lies along them (the
    jaws grip its end faces). A box is measured in the grasp frame. Anything else is a mesh: convex pieces, in the grasp
    frame, approximating the part (V-HACD). The defaults are the vial cap on the cell (31.75 mm across, 15.7 mm tall,
    5 g in the twin). friction is the part's coefficients against the printed pads (static, dynamic): see material.py."""

    shape: Literal["cylinder", "box", "mesh"] = "cylinder"
    diameter_mm: float = Field(31.75, gt=0)  # cylinder
    length_mm: float = Field(15.7, gt=0)  # cylinder, along its axis
    axis: CylinderAxis = "z"  # cylinder
    width_mm: float = Field(10, gt=0)  # box, along the jaws' closing direction
    depth_mm: float = Field(10, gt=0)  # box, across the jaws
    height_mm: float = Field(10, gt=0)  # box
    pieces: list[Piece] | None = None  # mesh
    mass_g: float = Field(5, gt=0)
    friction: tuple[float, float] = (0.6, 0.5)

    @model_validator(mode="after")
    def _mesh_has_pieces(self) -> "Part":
        if self.shape == "mesh" and not self.pieces:
            raise ValueError("a mesh part needs its convex pieces")
        return self

    @property
    def extent_mm(self) -> tuple[float, float, float]:
        """Size along the closing direction, across it, and height."""
        if self.shape == "box":
            return self.width_mm, self.depth_mm, self.height_mm
        if self.shape == "mesh":
            lo, hi = pieces_bounds(self.pieces)
            return tuple(float(v) for v in hi - lo)
        d, length = self.diameter_mm, self.length_mm
        return {"z": (d, d, length), "y": (d, length, d), "x": (length, d, d)}[self.axis]

    @property
    def round_from_above(self) -> bool:
        """An upright cylinder: a groove can centre it, and its yaw doesn't matter."""
        return self.shape == "cylinder" and self.axis == "z"
