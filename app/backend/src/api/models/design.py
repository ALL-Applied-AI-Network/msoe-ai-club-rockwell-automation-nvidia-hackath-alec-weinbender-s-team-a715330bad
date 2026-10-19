"""Finger templates, their parameter ranges, and a design: one template plus values for its parameters.

The ranges assume large parts. They need re-ranging for the twin's 12 mm gripper stroke (see CONTEXT.md).
"""

from pydantic import BaseModel

SPACE: dict[str, dict[str, tuple[float, float]]] = {
    "flat_pad": {"finger_length": (15, 60), "pad_width": (8, 40), "pad_thickness": (2, 10), "pad_friction_texture": (0, 1)},
    "v_groove": {"finger_length": (15, 60), "groove_angle": (60, 140), "groove_depth": (2, 20), "pad_width": (8, 40)},
    "pocket": {"finger_length": (15, 60), "pocket_clearance": (0, 6), "pocket_depth": (2, 25), "pocket_radius_scale": (0.8, 1.2)},
}
TEMPLATES = list(SPACE)


class Design(BaseModel):
    template: str
    params: dict[str, float]


def clamp_params(template: str, params: dict) -> dict[str, float]:
    """Every parameter of the template, clamped to its range. Missing ones get the middle of the range."""
    out = {}
    for name, (lo, hi) in SPACE[template].items():
        value = params.get(name, (lo + hi) / 2)
        out[name] = min(hi, max(lo, float(value)))
    return out
