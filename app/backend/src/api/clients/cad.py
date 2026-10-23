"""CAD files, through CadQuery (OpenCascade): a part in from STEP or STL, and a finger pair out as STEP and STL.

The finger geometry itself is built in api/models/finger.py (the simulated convex solids) and api/models/finger_cad.py
(the printable solid), so the files, the simulated pieces and the 3D preview all come from the same CadQuery solids.
"""

import datetime
import logging
import re
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import cadquery as cq
import numpy as np
from fpdf import FPDF
from fpdf.fonts import FontFace
from OCP.RWStl import RWStl

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.export_check import ExportCheck, run_checks
from api.models.family import FAMILIES
from api.models.finger_cad import PrintableFinger, print_orientation, print_pose, printable_pair
from api.models.material import material_from_text
from api.models.part import Part
from api.models.part_cad import PartCad, PartMesh, measure
from api.models.print_sheet import PrintSheet

logger = logging.getLogger(__name__)

STL_TOLERANCE_MM = 0.01  # chordal deviation of the exported STL
PART_TOLERANCE_MM = 0.05  # tessellating a STEP part for measuring and decomposition
MM_PER_INCH = 25.4
SOLIDWORKS_SUFFIXES = (".sldprt", ".sldasm", ".slddrw")
SOLIDWORKS_HINT = "In SolidWorks: File > Save As > STEP."
# Where a STEP file names materials: material designations and product names/descriptions.
STEP_MATERIAL_TEXT = re.compile(r"(?:MATERIAL_DESIGNATION|PRODUCT|DESCRIPTIVE_REPRESENTATION_ITEM)\s*\(\s*'([^']*)'(?:\s*,\s*'([^']*)')?")


class UnsupportedCadFormatError(ValueError):
    """A file the app doesn't read (a native SolidWorks file, say). The message says what to send instead."""


@dataclass
class FingerExport:
    """A design's printable files and the checks they passed. files: "step" (the pair), "stl_left", "stl_right",
    "print_sheet" -> path. A failed blocking check means the files must not be offered for download. orientation is the
    print orientation advice, with its supports note, as the print sheet gives it."""

    files: dict[str, Path]
    checks: list[ExportCheck] = field(default_factory=list)
    orientation: str = ""

    @property
    def blocked(self) -> list[ExportCheck]:
        return [check for check in self.checks if check.blocking and not check.ok]


class CadClient(Protocol):
    backend: str

    def read_part(self, filename: str, content: bytes, units: Literal["mm", "in"] = "mm") -> tuple[PartCad, PartMesh]:
        """A STEP (exact solids, units from the file) or STL (a mesh in `units`) of the part, measured in the CAD frame.
        Raises UnsupportedCadFormatError for a format we don't read, ValueError for a file that can't be read."""
        ...

    def export(
        self, part: Part, design: Design, gripper: Gripper, *, finger_id: str, stem: Path, sheet: PrintSheet | None = None
    ) -> FingerExport:
        """Write the design's printable fingers next to `stem` (stem.step, stem_L.stl, ...) for this gripper's mount, with
        `finger_id` (e.g. EXP-0042-D1) engraved plus -L / -R, and the print sheet if one is given. The files are written
        even when a blocking check fails; the caller must not offer them then. Raises ValueError for the stock design."""
        ...

    def close(self) -> None: ...


class CadQueryCad:
    """Both fingers, placed as they sit on the gripper with the jaws open (the second is the first mirrored), in the
    gripper frame: mm, x along the jaw travel, z up toward the wrist, fingertips at z = 0."""

    backend = "cadquery"

    def read_part(self, filename: str, content: bytes, units: Literal["mm", "in"] = "mm") -> tuple[PartCad, PartMesh]:
        suffix = Path(filename).suffix.lower()
        if suffix in SOLIDWORKS_SUFFIXES:
            raise UnsupportedCadFormatError(f"{filename}: native SolidWorks files can't be read. {SOLIDWORKS_HINT}")
        if suffix not in (".step", ".stp", ".stl"):
            raise UnsupportedCadFormatError(f"{filename}: send a STEP (.step, .stp) or STL (.stl) file. {SOLIDWORKS_HINT}")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"part{suffix}"
            path.write_bytes(content)
            if suffix == ".stl":
                vertices, triangles, volume = _stl_mesh(path, filename)
                scale = MM_PER_INCH if units == "in" else 1.0
                return measure(filename, "stl", vertices * scale, triangles, volume * scale**3)
            return _read_step(path, filename, content)

    def export(
        self, part: Part, design: Design, gripper: Gripper, *, finger_id: str, stem: Path, sheet: PrintSheet | None = None
    ) -> FingerExport:
        """The STEP holds the pair as mounted, jaws open, for review in CAD; each STL holds one finger lying as it should be
        printed (finger_cad.print_pose), for the slicer."""
        if design.kind == "stock":
            raise ValueError("the stock design can't be exported: the stock fingers are aluminium and already on the robot")
        started = time.perf_counter()
        fingers = printable_pair(part, design, gripper, finger_id=finger_id)
        checks = run_checks(part, design, gripper, fingers)
        orientation = print_orientation(fingers[0])
        stem.parent.mkdir(parents=True, exist_ok=True)
        files = {
            key: stem.parent / f"{stem.name}{suffix}"
            for key, suffix in (("step", ".step"), ("stl_left", "_L.stl"), ("stl_right", "_R.stl"))
        }
        _write_pair_step(files["step"], fingers, gripper.stroke_mm, finger_id)
        for key, finger in zip(("stl_left", "stl_right"), fingers, strict=True):
            cq.exporters.export(print_pose(finger), str(files[key]), tolerance=STL_TOLERANCE_MM, angularTolerance=0.1)
        if sheet is not None:
            files["print_sheet"] = stem.parent / f"{stem.name}_print_sheet.pdf"
            _write_print_sheet(files["print_sheet"], sheet, part, fingers, checks, orientation)
        blocked = [check.name for check in checks if check.blocking and not check.ok]
        logger.info("exported %s to %s in %.1f s; blocking failures: %s", finger_id, stem, time.perf_counter() - started, blocked or "none")
        return FingerExport(files=files, checks=checks, orientation=orientation)

    def close(self) -> None:
        pass


def create_cad_client() -> CadClient:
    return CadQueryCad()


def _write_pair_step(path: Path, fingers: Sequence[PrintableFinger], stroke: float, finger_id: str) -> None:
    """Both fingers as mounted with the jaws open, as two bodies named by their IDs: the left moved out along +x by the
    stroke, the right (already mirrored) along -x. An assembly, so CAD tools show two named parts rather than one blob."""
    assembly = cq.Assembly(name=finger_id)
    for finger in fingers:
        shift = stroke if finger.side == "L" else -stroke
        assembly.add(finger.solid.translate(cq.Vector(shift, 0, 0)), name=f"{finger_id}-{finger.side}")
    assembly.export(str(path), exportType="STEP")


# fpdf2's built-in fonts cover Latin-1 only: the usual typographic characters are swapped for plain ones, the rest for "?".
_LATIN1 = str.maketrans(
    {
        "\N{EM DASH}": "-",
        "\N{EN DASH}": "-",
        "\N{MINUS SIGN}": "-",
        "\N{LESS-THAN OR EQUAL TO}": "<=",
        "\N{GREATER-THAN OR EQUAL TO}": ">=",
        "\N{GREEK SMALL LETTER MU}": "\N{MICRO SIGN}",
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{RIGHT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
        "\N{HORIZONTAL ELLIPSIS}": "...",
        "\N{RIGHTWARDS ARROW}": "->",
    }
)
_LABEL_MM = 34.0
_LINE_MM = 4.2
_BLANK = "_" * 24  # a line to write on


def _write_print_sheet(
    path: Path, sheet: PrintSheet, part: Part, fingers: Sequence[PrintableFinger], checks: Sequence[ExportCheck], orientation: str
) -> None:
    """The one-page print sheet: what to print, in what, lying which way, and what still needs confirming."""
    pdf = FPDF(format="letter")
    pdf.set_title(f"Print sheet {sheet.finger_id}")
    pdf.set_margins(15, 12, 15)
    pdf.set_auto_page_break(True, margin=10)
    pdf.add_page()
    if sheet.sim_backend == "mock":
        pdf.set_fill_color(190, 25, 25)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", "B", 22)
        pdf.cell(pdf.epw, 12, "MOCK SIM: not a prediction", align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 9)
        note = "Scored by the geometry-only mock simulator, not physics. Print it to test the pipeline, not to expect its success rate."
        pdf.cell(pdf.epw, 6, note, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(2)
    pdf.set_fill_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(pdf.epw, 8, _pdf_text(f"Print sheet: {sheet.finger_id}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 8)
    header = f"{datetime.date.today().isoformat()} | {sheet.sim_backend} sim | {path.name}"
    pdf.cell(pdf.epw, 4, _pdf_text(header), new_x="LMARGIN", new_y="NEXT")
    engraved = [f"{f.engraving.text} ({'left, +x jaw' if f.side == 'L' else 'right, -x jaw'})" for f in fingers if f.engraving.text]
    missing = [f"{f.side}: {f.engraving.detail}" for f in fingers if not f.engraving.text]
    ids = ", ".join(engraved) + ("; not engraved, so label by hand: " + "; ".join(missing) if missing else "")
    _section(pdf, "Identity", [("Experiment", sheet.experiment), ("Design", sheet.design_label), ("Finger IDs (engraved)", ids)])

    _heading(pdf, "Parameters")
    pdf.set_font("helvetica", "", 8)
    if sheet.params:
        family = FAMILIES.get(str(sheet.params.get("family", "")))
        fields = family.params.model_fields if family and family.params else {}
        heading = FontFace(emphasis="BOLD", fill_color=(235, 235, 235))
        with pdf.table(
            col_widths=(22, 14, 64), line_height=3.8, text_align=("LEFT", "RIGHT", "LEFT"), padding=0.8, headings_style=heading
        ) as table:
            table.row(["Parameter", "Value", "What it sets"])
            for name, value in sheet.params.items():
                if name == "family":
                    continue
                label, unit = _split_unit(name)
                shown = f"{value:.2f} {unit}".strip() if isinstance(value, int | float) else str(value)
                table.row([_pdf_text(label), _pdf_text(shown), _pdf_text(fields[name].description or "" if name in fields else "")])
    else:
        pdf.multi_cell(pdf.epw, _LINE_MM, _pdf_text(f"{sheet.design_label}: a baseline built from the part, with no family parameters."))

    static, dynamic = part.friction
    pad_static, pad_dynamic = sheet.pad_friction
    material = (
        f"{sheet.material}. The sim assumed friction {static:.2f} static / {dynamic:.2f} dynamic between the part and this pad "
        f"(the pad's own: {pad_static:.2f} / {pad_dynamic:.2f}). Print in this material: another grips differently, and the "
        "prediction no longer applies."
    )
    infill = f"{sheet.infill_percent}%" + (" (solid: the pad takes the grip force)" if sheet.infill_percent >= 100 else "")
    settings = [
        ("Material", material),
        ("Infill and walls", f"{infill}; {sheet.walls} walls (perimeters)"),
        ("Orientation", orientation),
        ("Print time", sheet.print_time or _BLANK),
        ("Filament", sheet.filament or _BLANK),
    ]
    _section(pdf, "Printing", settings)
    pose = "; ".join(_pose_item(key, value) for key, value in sheet.grasp_pose.items()) or "not given"
    _section(pdf, "Grasp pose", [("Robot", pose)])
    marks = {(True, True): "PASS", (False, True): "FAIL", (True, False): "NOTE", (False, False): "NOTE"}
    _section(pdf, "Export checks", [(f"{marks[(c.ok, c.blocking)]}  {c.name}", c.detail) for c in checks], size=7)

    caveats = [*sheet.caveats]
    if missing:
        caveats.append("The ID isn't engraved: write it on the finger before it's tested.")
    caveats.append("No printed finger goes on the robot before it's reviewed in the app.")
    _heading(pdf, "Caveats")
    pdf.set_font("helvetica", "", 9)
    for caveat in caveats:
        pdf.multi_cell(pdf.epw, _LINE_MM, _pdf_text(f"- {caveat}"), new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def _heading(pdf: FPDF, title: str) -> None:
    pdf.ln(1.5)
    pdf.set_font("helvetica", "B", 10.5)
    pdf.cell(pdf.epw, 5.5, title, border="B", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _section(pdf: FPDF, title: str, rows: Sequence[tuple[str, str]], size: float = 9) -> None:
    """A heading, then label: value rows, the values wrapping in their own column."""
    _heading(pdf, title)
    for label, value in rows:
        pdf.set_font("helvetica", "B", size)
        pdf.cell(_LABEL_MM, _LINE_MM, _pdf_text(label))
        pdf.set_font("helvetica", "", size)
        pdf.multi_cell(pdf.epw - _LABEL_MM, _LINE_MM, _pdf_text(value), new_x="LMARGIN", new_y="NEXT")


def _pose_item(key: str, value) -> str:
    """("tip_height_mm", 4.0) -> "tip height 4.0 mm". A job covering several resting poses lists each pose's grasp:
    ("poses", [...]) -> "pose 1 (lying on its side, weight 0.62): grasp angle 0 deg, ...; pose 2 (...): ..."."""
    if key == "poses" and isinstance(value, list):
        return "; ".join(
            f"pose {i} ({pose.get('resting_pose')}, weight {pose.get('weight')}): "
            + ", ".join(_pose_item(k, v) for k, v in pose.items() if k not in ("resting_pose", "weight"))
            for i, pose in enumerate(value, 1)
        )
    label, unit = _split_unit(key)
    return f"{label} {value} {unit}".strip()


def _split_unit(name: str) -> tuple[str, str]:
    """pad_width_mm -> ("pad width", "mm")."""
    for suffix, unit in (("_mm", "mm"), ("_deg", "deg")):
        if name.endswith(suffix):
            return name[: -len(suffix)].replace("_", " "), unit
    return name.replace("_", " "), ""


def _pdf_text(text: str) -> str:
    return str(text).translate(_LATIN1).encode("latin-1", "replace").decode("latin-1")


def _read_step(path: Path, filename: str, content: bytes) -> tuple[PartCad, PartMesh]:
    try:
        solids = cq.importers.importStep(str(path)).solids().vals()
    except Exception as e:  # OpenCascade's reader raises its own exception types
        raise ValueError(f"{filename}: not a readable STEP file ({e})") from e
    if not solids:
        raise ValueError(f"{filename}: the STEP file has no solids")
    compound = cq.Compound.makeCompound(solids)
    vertices, triangles = compound.tessellate(PART_TOLERANCE_MM, 0.2)
    volumes = [s.Volume() for s in solids]
    total = sum(volumes)
    centre = sum((np.array(s.Center().toTuple()) * v for s, v in zip(solids, volumes, strict=True)), np.zeros(3)) / total
    names = " ".join(" ".join(m) for m in STEP_MATERIAL_TEXT.findall(content.decode("latin-1", errors="ignore")))
    return measure(
        filename,
        "step",
        np.array([v.toTuple() for v in vertices]),
        np.array(triangles),
        total,
        centre_of_mass=tuple(centre),
        face_types=dict(Counter(face.geomType() for face in compound.Faces())),
        material_hint=material_from_text(names),
    )


def _stl_mesh(path: Path, filename: str) -> tuple[np.ndarray, np.ndarray, float]:
    mesh = RWStl.ReadFile_s(str(path))
    if mesh is None or mesh.NbTriangles() == 0:
        raise ValueError(f"{filename}: not a readable STL file")
    vertices = np.array([(p.X(), p.Y(), p.Z()) for p in (mesh.Node(i) for i in range(1, mesh.NbNodes() + 1))])
    triangles = np.array([mesh.Triangle(i).Get() for i in range(1, mesh.NbTriangles() + 1)]) - 1  # 1-based
    a, b, c = (vertices[triangles[:, k]] for k in range(3))
    volume = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)  # signed; a closed mesh gives its volume
    return vertices, triangles, volume
