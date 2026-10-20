"""The search space for one part: the design parameters, mapped from a unit cube so that every point is a finger that fits.

The ranges depend on the part and on each other: a deeper groove seats the part deeper, which leaves less slack before
the jaws can't close far enough to grip, and a higher grip leaves less pad for a lead-in. So from_unit() sets the
parameters in order, each within the range the earlier ones leave. The optimizer works on the unit cube; to_unit()
inverts the mapping. Groove parameters only exist for parts that are round from above: against a flat side a groove
only takes slack away.
"""

import math
from collections.abc import Sequence

from api.models.design import Design
from api.models.finger import BLADE_MM, ENVELOPE_MM, SEAT_GAP_MM, SQUEEZE_MM, STROKE_MM, seat_distance, v_profile
from api.models.part import Part

MIN_SLACK_MM = 0.5
JAW_MARGIN_MM = 0.2  # gripping, the jaws stop at least this far short of fully closed
MIN_TIP_MM = 1.0  # fingertips above the table


class SearchSpace:
    def __init__(self, part: Part):
        self.part = part
        groove = ["groove_angle_deg", "groove_depth_mm"] if part.round_from_above else []
        self.names = ["pad_width_mm", *groove, "slack_mm", "tip_height_mm", "lead_in_mm"]

    def from_unit(self, unit: Sequence[float]) -> Design:
        params: dict[str, float] = {}
        for name, u in zip(self.names, unit, strict=True):
            lo, hi = self._range(name, params)
            params[name] = lo + min(1.0, max(0.0, float(u))) * (hi - lo)
        return Design(kind="search", params=params)

    def to_unit(self, design: Design) -> list[float]:
        params: dict[str, float] = {}
        unit = []
        for name in self.names:
            lo, hi = self._range(name, params)
            value = params[name] = design.params[name]
            unit.append(min(1.0, max(0.0, (value - lo) / (hi - lo))) if hi > lo else 0.0)
        return unit

    def bounds(self) -> dict[str, tuple[float, float]]:
        """Each parameter's widest range for this part (the coupling narrows it in places): for people and prompts."""
        loosest = {"pad_width_mm": self._range("pad_width_mm", {})[1], "groove_angle_deg": 60.0, "groove_depth_mm": 0.0}
        loosest["tip_height_mm"] = MIN_TIP_MM
        return {name: self._range(name, loosest) for name in self.names}

    def _range(self, name: str, p: dict[str, float]) -> tuple[float, float]:
        x, y, height = self.part.extent_mm
        if name == "pad_width_mm":  # scaled to the part, within the room beside the gripper
            widest = 2 * (ENVELOPE_MM[1] - 1)
            lo = max(BLADE_MM[1], min(0.4 * y, widest - 10))
            return lo, min(widest, max(lo + 4, 1.2 * y))
        if name == "groove_angle_deg":
            return 60.0, 180.0
        if name == "groove_depth_mm":
            return 0.0, self._max_depth(p["pad_width_mm"], p["groove_angle_deg"])
        if name == "slack_mm":
            profile = v_profile(p["pad_width_mm"], p.get("groove_angle_deg", 180.0), p.get("groove_depth_mm", 0.0))
            room = seat_distance(self.part, profile) - x / 2 + STROKE_MM - SQUEEZE_MM - JAW_MARGIN_MM
            return MIN_SLACK_MM, max(MIN_SLACK_MM, room)
        if name == "tip_height_mm":
            return MIN_TIP_MM, max(MIN_TIP_MM, min(0.6 * height, height - 3))
        if name == "lead_in_mm":
            return 0.0, max(0.0, min(4.0, height - p["tip_height_mm"] - 2))
        raise KeyError(name)

    def _max_depth(self, width: float, angle_deg: float) -> float:
        """The deepest groove that leaves a 1 mm shoulder each side, keeps the gripped part's centre SEAT_GAP_MM in front of
        the face (so the fingers don't meet), and still leaves MIN_SLACK_MM of slack."""
        r = self.part.extent_mm[0] / 2
        cap = min(0.8 * r, (width / 2 - 1) / math.tan(math.radians(angle_deg / 2)))
        if cap <= 0:
            return 0.0
        need = max(SEAT_GAP_MM, r - (STROKE_MM - SQUEEZE_MM - JAW_MARGIN_MM - MIN_SLACK_MM))

        def fits(depth: float) -> bool:
            return seat_distance(self.part, v_profile(width, angle_deg, depth)) >= need

        if fits(cap):
            return cap
        lo, hi = 0.0, cap
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if fits(mid) else (lo, mid)
        return lo
