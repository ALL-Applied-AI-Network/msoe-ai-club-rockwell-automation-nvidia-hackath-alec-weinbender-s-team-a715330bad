"""The one-page print sheet that goes with a printable finger: how to print it so it matches what was simulated.
Rendered to PDF by the CAD client (workstream E fills in the rendering and the orientation advice)."""

from typing import Any

from pydantic import BaseModel

from api.models.job_spec import SimBackend


class PrintSheet(BaseModel):
    experiment: str  # "vial-cap_2026-10-19 (EXP-0042)"
    finger_id: str  # EXP-0042-D1; the sides add -L / -R
    design_label: str
    params: dict[str, Any] | None = None  # the family parameters, for the record
    material: str  # pad material, e.g. "PLA/PETG": must match the friction the sim assumed
    pad_friction: tuple[float, float]
    sim_backend: SimBackend
    grasp_pose: dict[str, Any] = {}
    infill_percent: int = 100  # solid: the pads take the grip force
    walls: int = 4
    print_time: str | None = None  # from the slicer, if available; else left blank
    filament: str | None = None
    caveats: list[str] = []  # e.g. "mount holes from the twin's photo reconstruction: confirm on the real jaw"
