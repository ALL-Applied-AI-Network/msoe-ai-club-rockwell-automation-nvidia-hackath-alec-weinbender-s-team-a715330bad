"""What the sim reports for one design across a batch of offsets: the raw outcomes every score is computed from.

Stored as they come, so any error model, bias, task or tolerance can be re-scored later without simulating again.
"""

from pydantic import BaseModel, model_validator

# The part's pose in the hand at the end of the lift, relative to the commanded gripper frame and to where a centred
# part would sit: dx, dy, dz in mm (gripper frame: x along the closing direction), tilt and yaw in degrees.
InHand = tuple[float, float, float, float, float]

# How far the part moved while the gripper came down, before the jaws closed: its centre's shift in the table plane in mm,
# and the angle it turned through in degrees.
Landing = tuple[float, float]

# A grasp that moved the part more than this before the jaws closed landed a finger on it. The sim may still report it
# held (the descent squeezed the part into the gap), but a real arm is as likely to knock the part away, so it scores as a
# miss (Task.success). Well above what a part left alone moves (it rests from the start of the approach).
LANDING_SHIFT_MM = 1.0
LANDING_TURN_DEG = 3.0


class Outcomes(BaseModel):
    held: list[bool]  # per offset: the part's centre rose more than 25 mm during the lift
    in_hand: list[InHand | None]  # per offset; None where it wasn't held (or wasn't simulated)
    held_after_transport: list[bool] | None = None  # per offset, when the task adds a transport move
    # per offset; None where it wasn't measured (not simulated, or a sim server from before 2026-10-26: then the whole
    # list is None, and nothing counts as landed)
    landing: list[Landing | None] | None = None

    @model_validator(mode="after")
    def _aligned(self) -> "Outcomes":
        n = len(self.held)
        lists = (self.in_hand, self.held_after_transport, self.landing)
        if any(values is not None and len(values) != n for values in lists):
            raise ValueError("held, in_hand, held_after_transport and landing need one entry per offset")
        return self

    @classmethod
    def dropped(cls, n: int, transport: bool = False) -> "Outcomes":
        """A design that wasn't simulated (it failed the geometry checks): every grasp counts as failed."""
        return cls(held=[False] * n, in_hand=[None] * n, held_after_transport=[False] * n if transport else None)

    def landed(self) -> list[bool]:
        """Per offset: whether a finger landed on the part (it moved past LANDING_SHIFT_MM or LANDING_TURN_DEG before
        the jaws closed). False where it wasn't measured."""
        if self.landing is None:
            return [False] * len(self.held)
        return [m is not None and (m[0] > LANDING_SHIFT_MM or m[1] > LANDING_TURN_DEG) for m in self.landing]


def landing_caveat(outcomes: list[Outcomes]) -> str | None:
    """What a page's numbers say about fingers landing on the part, from the outcomes they're scored on: how many held
    grasps count as misses for it, or that it wasn't checked (outcomes from before the sim measured it). None when there
    is nothing to say (no grasp was simulated)."""
    measured = [out for out in outcomes if out.landing is not None]
    if not measured:
        return (
            "a finger landing on the part before the jaws close isn't checked in this run (its sim server predates the "
            "check), so it can count as a hold"
            if any(any(out.held) for out in outcomes)
            else None
        )
    held = sum(sum(out.held) for out in measured)
    landed = sum(h and m for out in measured for h, m in zip(out.held, out.landed(), strict=True))
    if not held:
        return None
    return (
        f"{landed} of {held} grasps the sim held count as misses: a finger landed on the part (moved it more than "
        f"{LANDING_SHIFT_MM:g} mm or {LANDING_TURN_DEG:g} deg) before the jaws closed"
    )
