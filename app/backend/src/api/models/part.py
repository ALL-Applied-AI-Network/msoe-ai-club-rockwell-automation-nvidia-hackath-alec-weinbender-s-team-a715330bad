from typing import Literal

from pydantic import BaseModel, Field


class Part(BaseModel):
    """The part to grasp, as it rests on the table: a cylinder or a box. Millimetres and grams; the sim server converts.

    The gripper comes from above and its jaws close along the part's width. A cylinder stands on an end (upright) or lies
    on its side with its axis across the jaws. A box is measured in the gripper's frame. The defaults are the vial cap on
    the cell (31.75 mm across, 15.7 mm tall, 5 g in the twin)."""

    shape: Literal["cylinder", "box"] = "cylinder"
    diameter_mm: float = Field(31.75, gt=0)  # cylinder
    length_mm: float = Field(15.7, gt=0)  # cylinder, along its axis
    upright: bool = True  # cylinder: standing on an end; False: lying with its axis across the jaws
    width_mm: float = Field(10, gt=0)  # box, along the jaws' closing direction
    depth_mm: float = Field(10, gt=0)  # box, across the jaws
    height_mm: float = Field(10, gt=0)  # box
    mass_g: float = Field(5, gt=0)

    @property
    def extent_mm(self) -> tuple[float, float, float]:
        """Size along the closing direction, across it, and height."""
        if self.shape == "box":
            return self.width_mm, self.depth_mm, self.height_mm
        d = self.diameter_mm
        return (d, d, self.length_mm) if self.upright else (d, self.length_mm, d)

    @property
    def round_from_above(self) -> bool:
        """An upright cylinder: a groove can centre it, and its yaw doesn't matter."""
        return self.shape == "cylinder" and self.upright
