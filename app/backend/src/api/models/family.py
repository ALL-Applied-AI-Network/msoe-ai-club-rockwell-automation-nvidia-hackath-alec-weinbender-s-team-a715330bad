"""Finger families: the kinds of finger the optimizer can design. Each family's parameters are a pydantic model, each
family is searched on its own (with its own GP), and the families' winners meet only in the final dense test.

A FamilyChoice is what the user sets for one family in input step 6: which parameters keep a narrowed range and which
are locked to one value. Parameters left alone search their full default range (api/models/search_space.py works out
what's feasible for the part). Locking every parameter turns the family into a single-design test ("test my own design").

Only built families can be run. FAMILIES also lists the planned ones, so the UI can show them as planned.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

FamilyName = Literal["vpad", "imprint", "cradle"]
GRIP_HEIGHT_FIELD = "tip_height_mm"  # the parameter a grasp's grip height (input step 5) locks in every family


class VPadParams(BaseModel):
    """V-pad: an offset contact pad whose face is flat or has a V groove down its middle, with a lead-in chamfer along its
    bottom inner edge. Lengths in mm, angles in degrees. Field order is the order search_space.py sets them in, each within
    the room the earlier ones leave."""

    family: Literal["vpad"] = "vpad"
    pad_width_mm: float = Field(gt=0, description="width of the contact pad, across the jaws")
    groove_angle_deg: float = Field(
        180.0,
        ge=60,
        le=180,
        description="included angle of the V groove in the pad face (180 = flat)",
        json_schema_extra={"applies_to": "upright cylinders"},
    )
    groove_depth_mm: float = Field(0.0, ge=0, description="depth of that groove", json_schema_extra={"applies_to": "upright cylinders"})
    slack_mm: float = Field(gt=0, description="gap between the pad face and the centred part, per side, with the jaws open")
    tip_height_mm: float = Field(gt=0, description="fingertip height above the table when gripping (where the fingers hold the part)")
    lead_in_mm: float = Field(0.0, ge=0, description="45 degree chamfer along the pad's bottom inner edge, guiding an off-centre part in")


# The params of every built family. Once a second family is built this becomes
# Annotated[VPadParams | OtherParams, Field(discriminator="family")].
FamilyParams = VPadParams


@dataclass(frozen=True)
class Family:
    name: FamilyName
    label: str
    status: Literal["built", "planned"]
    description: str
    params: type[BaseModel] | None  # None while planned
    only_for: str | None = None  # the parts it applies to, if not all

    @property
    def fields(self) -> list[str]:
        """The parameter names, in search order (without the 'family' tag)."""
        return [] if self.params is None else [name for name in self.params.model_fields if name != "family"]


FAMILIES: dict[str, Family] = {
    "vpad": Family(
        "vpad",
        "V-pad",
        "built",
        "flat pads and V-grooves of any angle, plus slack, width, height and lead-in",
        VPadParams,
    ),
    "imprint": Family(
        "imprint",
        "Imprint with clearance",
        "planned",
        "a carved copy of the part, enlarged by a clearance per direction; the fixed imprint baseline is this family at zero clearance",
        None,
    ),
    "cradle": Family(
        "cradle",
        "Curved cradle",
        "planned",
        "a rounded scoop that stops a lying cylinder from rolling",
        None,
        only_for="lying cylinders",
    ),
}


class ParamRange(BaseModel):
    lo: float
    hi: float

    @model_validator(mode="after")
    def _ordered(self) -> "ParamRange":
        if self.hi < self.lo:
            raise ValueError(f"range {self.lo:g}..{self.hi:g} is backwards")
        return self


class FamilyChoice(BaseModel):
    """One ticked family in input step 6: user ranges (narrowed or widened; clipped to what's buildable later) and locked
    values. A parameter can have a range or a lock, not both."""

    family: FamilyName = "vpad"
    ranges: dict[str, ParamRange] = {}
    locks: dict[str, float] = {}

    @model_validator(mode="after")
    def _known_fields(self) -> "FamilyChoice":
        family = FAMILIES[self.family]
        if family.status != "built":
            raise ValueError(f"the {family.label} family is planned, not built yet")
        unknown = sorted((set(self.ranges) | set(self.locks)) - set(family.fields))
        if unknown:
            raise ValueError(f"{family.label} has no parameter(s) {', '.join(unknown)}; it has {', '.join(family.fields)}")
        both = sorted(set(self.ranges) & set(self.locks))
        if both:
            raise ValueError(f"{', '.join(both)}: give a range or a locked value, not both")
        return self

    @property
    def params_model(self) -> type[BaseModel]:
        return FAMILIES[self.family].params

    def with_grip_height(self, grip_height_mm: float | None) -> "FamilyChoice":
        """This choice with the grasp step's grip height (GraspChoice.grip_height_mm) locked onto GRIP_HEIGHT_FIELD, which
        it fixes in every family that has one. It replaces any range or lock set for that field in step 6, since the grasp
        it was picked for depends on it. None leaves the choice as it is."""
        if grip_height_mm is None or GRIP_HEIGHT_FIELD not in FAMILIES[self.family].fields:
            return self
        ranges = {name: r for name, r in self.ranges.items() if name != GRIP_HEIGHT_FIELD}
        return FamilyChoice(family=self.family, ranges=ranges, locks={**self.locks, GRIP_HEIGHT_FIELD: grip_height_mm})
