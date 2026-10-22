"""The UWM lab's parts: the organizers' CAD of the objects on the real cell (the repo's cad/ folder, docs/07-cad-models.md),
loaded into every database at startup, so the parts library is never empty, even before anyone uploads a part. Their ids
are fixed, so loading them again finds them instead of adding copies."""

from dataclasses import dataclass

from api.models.material import Material

LAB_PREFIX = "lab-"  # uploaded parts get 12 hex digits, so they never start with this


@dataclass(frozen=True)
class LabPart:
    id: str
    file: str  # in the repo's cad/ folder; STEP where there is one, else the STL (in mm)
    name: str  # what the parts library calls it
    material: Material | None = None  # only where it's known; the user confirms the rest, as for an upload


LAB_PARTS: tuple[LabPart, ...] = (
    LabPart("lab-m6-screw", "ISO10642-M6x30-countersunk-screw.step", "M6 × 30 countersunk screw", "steel"),
    LabPart("lab-bin", "manipbench-bin-50x50x55.step", "Bin, 50 × 50 × 55 mm"),
    LabPart("lab-cube-10mm", "manipbench-cube-10mm.step", "Cube, 10 mm"),
    LabPart("lab-cube-16mm", "manipbench-cube-16mm.step", "Cube, 16 mm"),
    LabPart("lab-vial", "csi-vial.stl", "Vial, Ø27 × 203 mm"),
    LabPart("lab-vial-cap", "csi-vial-cap.stl", "Vial cap, Ø32 mm"),
)


def is_lab_part(part_id: str) -> bool:
    return part_id.startswith(LAB_PREFIX)
