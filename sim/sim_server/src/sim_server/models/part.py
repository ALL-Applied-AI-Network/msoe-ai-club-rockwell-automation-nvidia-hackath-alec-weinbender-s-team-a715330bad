from typing import Literal

from pydantic import BaseModel, ConfigDict


class Part(BaseModel):
    """The part, in metres and kilograms. size is its extent in its own nominal frame: along the jaws' closing direction,
    across it, and height. A cylinder's axis is "z" when it stands on an end, "y" when it lies across the jaws."""

    model_config = ConfigDict(frozen=True)

    shape: Literal["cylinder", "box"]
    size: tuple[float, float, float]
    mass: float
    cylinder_axis: Literal["z", "y"] | None = None

    @property
    def width(self) -> float:
        """Extent along the jaws' closing direction at the nominal pose."""
        return self.size[0]

    @property
    def height(self) -> float:
        return self.size[2]
