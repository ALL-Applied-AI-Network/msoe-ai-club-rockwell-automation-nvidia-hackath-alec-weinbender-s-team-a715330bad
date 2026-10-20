"""The search space for one part, family and gripper: the design parameters, mapped from a unit cube so that every point
is a finger that fits.

The ranges depend on the part and on each other: a deeper groove seats the part deeper, which leaves less slack before
the jaws can't close far enough to grip, and a higher grip leaves less pad for a lead-in. So from_unit() sets the
parameters in the params model's field order, each within the range the earlier ones leave. The optimizer works on the
unit cube; to_unit() inverts the mapping. Groove parameters only apply to parts that are round from above (against a
flat side a groove only takes slack away): elsewhere they stay at their defaults and aren't searched.

Each parameter has two ranges at every point:

- its limits: what's buildable with this gripper (stroke, free space beside it, kept mount) and the part's clearance on
  the table. User ranges are intersected with them (an empty intersection becomes the nearest limit) and locked values
  are clipped into them, per design, so a lock can't produce a finger that doesn't fit;
- its default range: the sensible part of the limits (pads scaled to the part, grips in its lower 60%), searched when
  the user leaves the parameter alone.

The user's choice (api/models/family.py: FamilyChoice) removes locked parameters from the cube: `names` is what's left.
"""

import math
from collections.abc import Callable, Sequence
from typing import NamedTuple

from pydantic import BaseModel

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.export_check import MIN_WALL_MM
from api.models.family import FAMILIES, FamilyChoice
from api.models.finger import (
    BRIDGE_MM,
    DEFAULT_GRIPPER,
    SEAT_GAP_MM,
    SQUEEZE_MM,
    TOP_CLEARANCE_MM,
    WALL_MM,
    seat_distance,
    v_profile,
)
from api.models.part import Part

MIN_SLACK_MM = 0.5
JAW_MARGIN_MM = 0.2  # gripping, the jaws stop at least this far short of fully closed
MIN_TIP_MM = 1.0  # fingertips above the table
MIN_PAD_MM = 2.0  # narrower pads print as fins
MIN_CONTACT_MM = 2.0  # pad face left on the part, between the grip height and the top of the lead-in
DEFAULT_GRIP_FRACTION = 0.6  # by default, grips are searched in the part's lower 60%
DEFAULT_MAX_LEAD_MM = 4.0
LOOSEST_HIGH = {"pad_width_mm"}  # a wide pad leaves later parameters the most room; for the rest it's the low end

# The parts a field's json_schema_extra "applies_to" means (api/models/family.py).
APPLIES_TO: dict[str, Callable[[Part], bool]] = {"upright cylinders": lambda part: part.round_from_above}


class ParamSummary(BaseModel):
    """One parameter's row in step 6: what's feasible for this part and gripper, what the user asked, what will be used.
    The ranges are the widest the coupled mapping reaches (each earlier parameter at its loosest); a given design's
    range can be narrower."""

    name: str
    description: str
    unit: str  # "mm" or "deg"
    applies: bool  # False where the parameter doesn't apply to this part (fixed at its default and not searched)
    default_range: tuple[float, float]  # what's searched when the user leaves it alone
    limits: tuple[float, float]  # what's buildable: user ranges and locks are clipped to this
    user_range: tuple[float, float] | None = None
    effective_range: tuple[float, float]  # what's searched: the user range clipped to the limits, or the default
    locked: float | None = None  # the user's locked value (effective_range holds it clipped)
    note: str | None = None  # e.g. "slack clipped to 4.4 mm: the stroke leaves no more"


class Limits(NamedTuple):
    """A parameter's range at one point of the mapping, given the parameters before it."""

    lo: float
    hi: float  # never below lo: when nothing fits, lo, which problems() then reports
    default: tuple[float, float]  # within lo..hi
    why_lo: str
    why_hi: str
    feasible: bool  # False when the caps fall below lo


class SearchSpace:
    """One family's designs for a part (as the gripper meets it) on a cell. choice: the user's ranges and locks (none: the
    full default space); gripper: the cell profile's (none: the UWM cell's); clearance_mm: the part's free space on the
    table (none: unlimited)."""

    def __init__(self, part: Part, choice: FamilyChoice | None = None, gripper: Gripper | None = None, clearance_mm: float | None = None):
        self.part = part
        self.choice = choice or FamilyChoice()
        self.gripper = gripper or DEFAULT_GRIPPER
        self.clearance_mm = clearance_mm
        self.family = FAMILIES[self.choice.family]
        self.fields = self.family.fields
        model_fields = self.family.params.model_fields
        self.defaults = {name: model_fields[name].default for name in self.fields if not model_fields[name].is_required()}
        self.applies = {name: _applies(part, model_fields[name].json_schema_extra) for name in self.fields}
        self.locks = {name: v for name, v in self.choice.locks.items() if self.applies[name]}
        self.ranges = {name: (r.lo, r.hi) for name, r in self.choice.ranges.items() if self.applies[name]}
        self.names = [name for name in self.fields if self.applies[name] and name not in self.locks]  # the free parameters
        self._extent = part.extent_mm

    def from_unit(self, unit: Sequence[float]) -> Design:
        """The design at a point of the unit cube (one coordinate per free parameter, in `names` order)."""
        u = dict(zip(self.names, (min(1.0, max(0.0, float(v))) for v in unit), strict=True))
        values = self._set(lambda name, lo, hi: lo + u[name] * (hi - lo))
        return Design(kind="search", params=self.family.params(**values))

    def to_unit(self, design: Design) -> list[float]:
        """The point of the unit cube a design maps from (0 where a parameter's range has collapsed to one value)."""
        unit = []

        def place(name: str, lo: float, hi: float) -> float:
            value = getattr(design.params, name)
            unit.append(min(1.0, max(0.0, (value - lo) / (hi - lo))) if hi > lo else 0.0)
            return value

        self._set(place, given=design.params)
        return unit

    def centre(self) -> Design:
        """The design in the middle of the cube, or the locked design when nothing is free: a representative design."""
        return self.from_unit([0.5] * len(self.names)) if self.names else self.locked_design()

    def locked_design(self) -> Design:
        """The single design of a fully locked family ("test my own design"), each lock clipped into its limits."""
        if self.names:
            raise ValueError(f"{self.family.label} still has free parameters: {', '.join(self.names)}")
        return Design(kind="locked", params=self.family.params(**self._set(lambda name, lo, hi: lo)))

    def bounds(self) -> dict[str, tuple[float, float]]:
        """Each free parameter's widest searched range for this part (the coupling narrows it in places): for people and
        prompts."""
        reach = self._reach(use_choice=True)
        return {name: reach[name][1] for name in self.names}

    def describe(self) -> list[ParamSummary]:
        """One summary per parameter of the family, in field order: default range, limits, the user's range or lock, what
        will be searched, and why anything was clipped."""
        widest, chosen = self._reach(use_choice=False), self._reach(use_choice=True)
        model_fields = self.family.params.model_fields
        out = []
        for name in self.fields:
            field, unit = model_fields[name], _unit(name)
            user = self.choice.ranges.get(name)
            user_range = None if user is None else (user.lo, user.hi)
            lock = self.choice.locks.get(name)
            if not self.applies[name]:
                fixed = self.defaults[name]
                note = None
                if user is not None or lock is not None:
                    applies_to = (field.json_schema_extra or {}).get("applies_to", "other parts")
                    note = f"{_label(name)} only applies to {applies_to}: fixed at {_num(fixed)} {unit}"
                out.append(
                    ParamSummary(
                        name=name,
                        description=field.description or "",
                        unit=unit,
                        applies=False,
                        default_range=(fixed, fixed),
                        limits=(fixed, fixed),
                        user_range=user_range,
                        effective_range=(fixed, fixed),
                        locked=lock,
                        note=note,
                    )
                )
                continue
            limits, effective = chosen[name]
            out.append(
                ParamSummary(
                    name=name,
                    description=field.description or "",
                    unit=unit,
                    applies=True,
                    default_range=widest[name][0].default,
                    limits=(widest[name][0].lo, widest[name][0].hi),
                    user_range=user_range,
                    effective_range=effective,
                    locked=lock,
                    note=_note(name, limits, user_range, lock, effective),
                )
            )
        return out

    def notes(self) -> list[str]:
        """Every clipping note, for the plan's warnings."""
        return [f"{self.family.label}: {s.note}" for s in self.describe() if s.note]

    def _set(self, choose: Callable[[str, float, float], float], given=None) -> dict[str, float]:
        """Set every field in order, each within the room the earlier ones leave: inapplicable ones to their defaults,
        locked ones to their lock clipped into the limits, free ones by choose(name, lo, hi) over their searched range.
        `given` (a params model) makes the locked fields keep its values, for inverting a design."""
        values: dict[str, float] = {}
        for name in self.fields:
            if not self.applies[name]:
                values[name] = self.defaults[name]
                continue
            limits = self._limits(name, values)
            if name in self.locks:
                lock = self.locks[name] if given is None else getattr(given, name)
                values[name] = min(limits.hi, max(limits.lo, lock))
            else:
                values[name] = choose(name, *self._searched(name, limits))
        return values

    def _searched(self, name: str, limits: Limits) -> tuple[float, float]:
        user = self.ranges.get(name)
        return limits.default if user is None else _intersect(user, (limits.lo, limits.hi))

    def _reach(self, use_choice: bool) -> dict[str, tuple[Limits, tuple[float, float]]]:
        """Each applicable field's limits and searched range with every earlier field at its loosest (see LOOSEST_HIGH):
        the widest the mapping goes. With use_choice=False, as if the user had set nothing."""
        values: dict[str, float] = {}
        out = {}
        for name in self.fields:
            if not self.applies[name]:
                values[name] = self.defaults[name]
                continue
            limits = self._limits(name, values)
            if use_choice and name in self.locks:
                v = min(limits.hi, max(limits.lo, self.locks[name]))
                searched = (v, v)
            elif use_choice and name in self.ranges:
                searched = _intersect(self.ranges[name], (limits.lo, limits.hi))
            else:
                searched = limits.default
            out[name] = (limits, searched)
            values[name] = searched[1] if name in LOOSEST_HIGH else searched[0]
        return out

    def _limits(self, name: str, p: dict[str, float]) -> Limits:
        """A V-pad parameter's limits and default range, given the parameters set before it (p)."""
        x, y, height = self._extent
        g, clearance = self.gripper, self.clearance_mm
        free_x, free_y = g.free_space_mm
        beside = "the space beside the gripper leaves no more"
        cleared = "the part's clearance leaves no more"

        def caps(*pairs: tuple[float, str], clear: float | None = None) -> list[tuple[float, str]]:
            return [*pairs, *([] if clear is None else [(clear, cleared)])]

        if name == "pad_width_mm":  # scaled to the part, within the room beside the gripper
            widest = 2 * (free_y - 1)
            lo = max(g.blade_mm[1], min(0.4 * y, widest - 10))
            default = (lo, min(widest, max(lo + 4, 1.2 * y)))
            clear = None if clearance is None else y + 2 * clearance
            return _limits(MIN_PAD_MM, "narrower pads print as fins", caps((widest, beside), clear=clear), default)
        if name == "groove_angle_deg":
            return _limits(60.0, "sharper grooves aren't modelled", [(180.0, "180 degrees is a flat pad")], (60.0, 180.0))
        if name == "groove_depth_mm":
            reach = free_x - x / 2 - WALL_MM - MIN_SLACK_MM
            clear = None if clearance is None else clearance - WALL_MM - MIN_SLACK_MM
            deepest = self._max_depth(p["pad_width_mm"], p["groove_angle_deg"])
            limits = caps((deepest, "a deeper groove leaves no shoulder or no slack"), (reach, beside), clear=clear)
            return _limits(0.0, "", limits, (0.0, 0.8 * x / 2))
        if name == "slack_mm":
            depth = p.get("groove_depth_mm", 0.0)
            profile = v_profile(p["pad_width_mm"], p.get("groove_angle_deg", 180.0), depth)
            room = seat_distance(self.part, profile) - x / 2 + g.stroke_mm - SQUEEZE_MM - JAW_MARGIN_MM
            reach = free_x - x / 2 - depth - WALL_MM
            clear = None if clearance is None else clearance - depth - WALL_MM
            limits = caps((room, "the stroke leaves no more"), (reach, beside), clear=clear)
            return _limits(MIN_SLACK_MM, "the pads need room to land beside the part", limits, (MIN_SLACK_MM, math.inf))
        if name == "tip_height_mm":
            mount = height + TOP_CLEARANCE_MM + BRIDGE_MM - (g.blade_mm[2] - g.mount_kept_mm)
            lo, why_lo = max((MIN_TIP_MM, "the fingertips stay off the table"), (mount, "a lower grip reaches the pad into the mount"))
            hi = height - MIN_CONTACT_MM
            default = (lo, min(DEFAULT_GRIP_FRACTION * height, height - 3))
            return _limits(lo, why_lo, [(hi, f"a higher grip leaves less than {MIN_CONTACT_MM:g} mm of pad on the part")], default)
        if name == "lead_in_mm":
            slack, depth = p["slack_mm"], p.get("groove_depth_mm", 0.0)
            pad = height - p["tip_height_mm"] - MIN_CONTACT_MM
            reach = free_x - x / 2 - slack - depth - WALL_MM
            clear = None if clearance is None else clearance - slack - depth - WALL_MM
            limits = caps(
                (pad, f"a longer lead-in leaves less than {MIN_CONTACT_MM:g} mm of pad on the part"), (reach, beside), clear=clear
            )
            return _limits(0.0, "", limits, (0.0, DEFAULT_MAX_LEAD_MM))
        raise KeyError(name)

    def _max_depth(self, width: float, angle_deg: float) -> float:
        """The deepest groove that leaves a printable shoulder each side (export_check.MIN_WALL_MM, so no design the search
        can propose is later blocked from export), keeps the gripped part's centre SEAT_GAP_MM in front of the face (so the
        fingers don't meet), and still leaves MIN_SLACK_MM of slack."""
        r = self._extent[0] / 2
        cap = (width / 2 - MIN_WALL_MM) / math.tan(math.radians(angle_deg / 2))
        if cap <= 0:
            return 0.0
        need = max(SEAT_GAP_MM, r - (self.gripper.stroke_mm - SQUEEZE_MM - JAW_MARGIN_MM - MIN_SLACK_MM))

        def fits(depth: float) -> bool:
            return seat_distance(self.part, v_profile(width, angle_deg, depth)) >= need

        if fits(cap):
            return cap
        lo, hi = 0.0, cap
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if fits(mid) else (lo, mid)
        return lo


def _limits(lo: float, why_lo: str, caps: list[tuple[float, str]], default: tuple[float, float]) -> Limits:
    hi, why_hi = min(caps, key=lambda cap: cap[0])
    feasible = hi >= lo
    hi = max(hi, lo)
    d_lo, d_hi = (min(hi, max(lo, v)) for v in default)
    return Limits(lo, hi, (d_lo, max(d_lo, d_hi)), why_lo, why_hi, feasible)


def _intersect(user: tuple[float, float], limits: tuple[float, float]) -> tuple[float, float]:
    """A user range within the limits; when they don't meet, the limit nearest to it."""
    lo, hi = max(user[0], limits[0]), min(user[1], limits[1])
    if lo <= hi:
        return lo, hi
    nearest = limits[0] if user[1] < limits[0] else limits[1]
    return nearest, nearest


def _applies(part: Part, extra) -> bool:
    applies_to = extra.get("applies_to") if isinstance(extra, dict) else None
    return applies_to is None or APPLIES_TO.get(applies_to, lambda _: True)(part)


def _note(name: str, limits: Limits, user: tuple[float, float] | None, lock: float | None, effective: tuple[float, float]) -> str | None:
    """Why the searched range or lock differs from what the user asked (or why nothing fits)."""
    label, unit = _label(name), _unit(name)
    if not limits.feasible:
        return f"no {label} fits: {limits.why_hi} (using {_num(limits.lo)} {unit})"
    if lock is not None:
        v = effective[0]
        if abs(v - lock) <= 1e-9:
            return None
        return f"{label} clipped to {_num(v)} {unit}: {limits.why_hi if lock > v else limits.why_lo}"
    if user is None:
        return None
    lo, hi = effective
    if lo == hi and (user[1] < limits.lo or user[0] > limits.hi):
        why = limits.why_lo if user[1] < limits.lo else limits.why_hi
        return f"{label} {_num(user[0])}-{_num(user[1])} {unit} isn't buildable: using {_num(lo)} {unit} ({why})"
    parts = []
    if hi < user[1] - 1e-9:
        parts.append(f"{label} clipped to {_num(hi)} {unit}: {limits.why_hi}")
    if lo > user[0] + 1e-9:
        parts.append(f"{label} raised to {_num(lo)} {unit}: {limits.why_lo}")
    return "; ".join(parts) or None


def _label(name: str) -> str:
    """slack_mm -> "slack", groove_angle_deg -> "groove angle"."""
    return name.removesuffix("_mm").removesuffix("_deg").replace("_", " ")


def _unit(name: str) -> str:
    return "deg" if name.endswith("_deg") else "mm"


def _num(v: float) -> str:
    return f"{round(v, 1):g}"
