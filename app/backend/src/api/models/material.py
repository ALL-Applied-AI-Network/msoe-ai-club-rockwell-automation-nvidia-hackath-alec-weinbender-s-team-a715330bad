"""Part materials: a density (for the mass) and a friction pair against the printed pads (for the sim's contacts).

Every number here is a textbook-level estimate, not a measurement: measure the real pair with a tilt test on the printed
pad and replace it. The surface option scales the friction (an oily part slips, a textured one grips).
"""

import re
from dataclasses import dataclass
from typing import Literal

Material = Literal["glass", "pla", "abs", "aluminium", "steel", "rubber", "other"]
Surface = Literal["smooth", "oily", "textured"]


@dataclass(frozen=True)
class MaterialProps:
    label: str
    density_g_cm3: float | None  # None: the user enters it ("other")
    friction: tuple[float, float] | None  # static, dynamic against printed PLA/PETG; None: the cell profile's pad friction
    keywords: tuple[str, ...] = ()  # how a STEP file's material text names it


MATERIALS: dict[str, MaterialProps] = {
    "glass": MaterialProps("Glass", 2.50, (0.40, 0.30), ("glass", "borosilicate", "quartz")),
    "pla": MaterialProps("PLA", 1.24, (0.50, 0.40), ("pla", "polylactic")),
    "abs": MaterialProps("ABS", 1.05, (0.50, 0.40), ("abs", "acrylonitrile")),
    "aluminium": MaterialProps("Aluminium", 2.70, (0.45, 0.35), ("aluminium", "aluminum", "6061", "7075", "alloy al")),
    "steel": MaterialProps("Steel", 7.85, (0.40, 0.30), ("steel", "stainless", "aisi", "s235", "1018")),
    "rubber": MaterialProps("Rubber", 1.10, (0.90, 0.80), ("rubber", "silicone", "nitrile", "epdm", "neoprene")),
    "other": MaterialProps("Other", None, None),
}
SURFACE_FACTORS: dict[str, float] = {"smooth": 1.0, "oily": 0.5, "textured": 1.2}


def pair_friction(material: Material | None, surface: Surface, pad_friction: tuple[float, float]) -> tuple[float, float]:
    """The part's (static, dynamic) friction against the printed pad: the material's estimate (the pad's own value for
    "other" or no material), scaled for the surface."""
    props = MATERIALS.get(material or "other")
    static, dynamic = props.friction or pad_friction
    factor = SURFACE_FACTORS[surface]
    return round(static * factor, 4), round(dynamic * factor, 4)


def material_from_text(text: str) -> Material | None:
    """The material a CAD file's text names (a STEP file's MATERIAL_DESIGNATION or product names), if any: the first
    material whose keyword appears as a word. Most exports carry none."""
    lowered = text.lower()
    for name, props in MATERIALS.items():
        if any(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", lowered) for word in props.keywords):
            return name
    return None
