"""Printable finger CAD. Only a placeholder so far: parametric OpenSCAD text. Replace it with a real CAD kernel
(e.g. CadQuery -> STEP/STL) behind the same interface."""

import json
import math
from typing import Protocol

from api.models.design import Design
from api.models.part import Part


class CadClient(Protocol):
    backend: str
    extension: str  # of the exported file, e.g. ".scad"

    def export(self, part: Part, design: Design) -> str: ...

    def close(self) -> None: ...


class OpenScadCad:
    backend = "openscad"
    extension = ".scad"

    def export(self, part: Part, design: Design) -> str:
        t, p = design.template, design.params
        length, width, thickness = p["finger_length"], p.get("pad_width", 20), p.get("pad_thickness", 6)
        body = f"cube([{width},{thickness + 10},{length}]);"
        if t == "v_groove":
            scale_y = math.tan(math.radians(p["groove_angle"] / 2))
            cut = p["groove_depth"] * 2
            body = (
                f"difference(){{cube([{width},20,{length}]); translate([{width / 2},20,{length * 0.7}]) rotate([90,0,0]) "
                f"rotate([0,0,45]) scale([1,{scale_y:.3f},1]) cylinder(h={cut},r1=0,r2={cut},center=true);}}"
            )
        elif t == "pocket":
            r = part.diameter_mm / 2 * p["pocket_radius_scale"] + p["pocket_clearance"]
            outer = max(width, 2 * r + 6)
            body = (
                f"difference(){{cube([{outer},{p['pocket_depth'] + 6},{length}]); "
                f"translate([{outer / 2},{p['pocket_depth'] + 6},{length * 0.7}]) sphere(r={r:.2f});}}"
            )
        return f"// {t} finger  params={json.dumps(p)}\n{body}\n"

    def close(self) -> None:
        pass


def create_cad_client() -> CadClient:
    return OpenScadCad()
