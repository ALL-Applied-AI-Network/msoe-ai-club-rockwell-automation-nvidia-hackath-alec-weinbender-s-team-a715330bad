"""What the sim reports for one design across a batch of offsets: the raw outcomes every score is computed from.

Stored as they come, so any error model, bias, task or tolerance can be re-scored later without simulating again.
"""

from pydantic import BaseModel, model_validator

# The part's pose in the hand at the end of the lift, relative to the commanded gripper frame and to where a centred
# part would sit: dx, dy, dz in mm (gripper frame: x along the closing direction), tilt and yaw in degrees.
InHand = tuple[float, float, float, float, float]


class Outcomes(BaseModel):
    held: list[bool]  # per offset: the part's centre rose more than 25 mm during the lift
    in_hand: list[InHand | None]  # per offset; None where it wasn't held (or wasn't simulated)
    held_after_transport: list[bool] | None = None  # per offset, when the task adds a transport move

    @model_validator(mode="after")
    def _aligned(self) -> "Outcomes":
        n = len(self.held)
        if len(self.in_hand) != n or (self.held_after_transport is not None and len(self.held_after_transport) != n):
            raise ValueError("held, in_hand and held_after_transport need one entry per offset")
        return self

    @classmethod
    def dropped(cls, n: int, transport: bool = False) -> "Outcomes":
        """A design that wasn't simulated (it failed the geometry checks): every grasp counts as failed."""
        return cls(held=[False] * n, in_hand=[None] * n, held_after_transport=[False] * n if transport else None)
