"""Printable finger CAD. For now OpenSCAD source of exactly the geometry that was simulated. Replace it with a real CAD
kernel (e.g. CadQuery -> STEP/STL, with the mount holes) behind the same interface."""

import json
from typing import Protocol

from api.models.finger import STROKE_MM, Finger


class CadClient(Protocol):
    backend: str
    extension: str  # of the exported file, e.g. ".scad"

    def export(self, finger: Finger, label: str) -> str: ...

    def close(self) -> None: ...


class OpenScadCad:
    """Both fingers as OpenSCAD polyhedra, placed as they sit on the gripper with the jaws open. The mount holes aren't
    cut yet (the real mount isn't confirmed), so the file is for review, not for printing."""

    backend = "openscad"
    extension = ".scad"

    def export(self, finger: Finger, label: str) -> str:
        pieces = "\n".join(
            # OpenSCAD wants faces clockwise seen from outside; ours are counter-clockwise
            f"    polyhedron(points={_numbers(piece.points)}, faces={json.dumps([list(t[::-1]) for t in piece.triangles])});"
            for piece in finger.pieces
        )
        return (
            f"// {label}\n"
            "// Gripper frame, mm: x along the jaw travel, z up toward the wrist, fingertips at z = 0. No mount holes yet.\n"
            f"module finger() {{\n  union() {{\n{pieces}\n  }}\n}}\n"
            f"translate([{STROKE_MM:g}, 0, 0]) finger();\n"
            f"mirror([1, 0, 0]) translate([{STROKE_MM:g}, 0, 0]) finger();\n"
        )

    def close(self) -> None:
        pass


def create_cad_client() -> CadClient:
    return OpenScadCad()


def _numbers(points) -> str:
    return json.dumps([[round(v, 4) for v in point] for point in points])
