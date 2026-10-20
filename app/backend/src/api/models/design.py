"""A finger design. The optimizer searches six numbers (see search_space.py); two baselines are built from the part alone."""

from typing import Literal

from pydantic import BaseModel

DesignKind = Literal["search", "stock", "imprint"]

PARAMS: dict[str, str] = {
    "pad_width_mm": "width of the contact pad, across the jaws",
    "groove_angle_deg": "included angle of the V groove in the pad face (180 = flat)",
    "groove_depth_mm": "depth of that groove",
    "slack_mm": "gap between the pad face and the centred part, per side, with the jaws open",
    "tip_height_mm": "fingertip height above the table when gripping (where the fingers hold the part)",
    "lead_in_mm": "45 degree chamfer along the pad's bottom inner edge, guiding an off-centre part in",
}


class Design(BaseModel):
    """What to build. 'search': a point of the search space, with the PARAMS above (the groove ones only for parts that
    are round from above). 'stock': the fingers already on the robot. 'imprint': a pocket shaped like the part, the
    usual hand-made design, which the judges' comparison needs."""

    kind: DesignKind = "search"
    params: dict[str, float] = {}
