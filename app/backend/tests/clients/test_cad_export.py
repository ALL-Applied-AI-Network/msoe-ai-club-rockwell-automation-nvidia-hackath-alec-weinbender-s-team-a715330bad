import cadquery as cq
import pytest
import trimesh

from api.clients.cad import CadQueryCad, FingerExport
from api.models import finger_cad
from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.part import Part
from api.models.print_sheet import PrintSheet

CAP = Part()
VPAD = Design(params={"pad_width_mm": 20, "groove_angle_deg": 90, "groove_depth_mm": 3, "slack_mm": 3, "tip_height_mm": 4, "lead_in_mm": 1})
FINGER_ID = "EXP-0042-D1"


def sheet(**changes) -> PrintSheet:
    values = {
        "experiment": "vial-cap_2026-10-19 (EXP-0042)",
        "finger_id": FINGER_ID,
        "design_label": "D1",
        "params": VPAD.params.model_dump(),
        "material": "PLA/PETG",
        "pad_friction": (0.6, 0.5),
        "sim_backend": "mock",
        "grasp_pose": {"approach": "top-down", "tip_height_mm": 4.0},
        "caveats": ["mount holes from the twin\N{RIGHT SINGLE QUOTATION MARK}s photo reconstruction: confirm on the real jaw"],
    }
    return PrintSheet(**(values | changes))


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> FingerExport:
    stem = tmp_path_factory.mktemp("export") / "vial-cap_EXP-0042_D1"
    return CadQueryCad().export(CAP, VPAD, Gripper(), finger_id=FINGER_ID, stem=stem, sheet=sheet())


def test_export_writes_the_pair_both_stls_and_the_print_sheet_named_from_the_stem(exported):
    names = {key: path.name for key, path in exported.files.items()}

    assert names == {
        "step": "vial-cap_EXP-0042_D1.step",
        "stl_left": "vial-cap_EXP-0042_D1_L.stl",
        "stl_right": "vial-cap_EXP-0042_D1_R.stl",
        "print_sheet": "vial-cap_EXP-0042_D1_print_sheet.pdf",
    }
    assert all(path.exists() for path in exported.files.values())
    assert [c.name for c in exported.checks] == ["solid", "matches sim", "min wall", "finger length", "engraved id"]
    assert exported.blocked == []
    assert exported.orientation.startswith("Lie each finger on its outer side")


def test_the_step_holds_both_fingers_as_two_named_bodies_mounted_with_the_jaws_open(exported):
    path = exported.files["step"]
    solids = cq.importers.importStep(str(path)).solids().vals()
    text = path.read_text(errors="ignore")

    assert path.read_bytes().startswith(b"ISO-10303-21")
    assert len(solids) == 2
    assert f"{FINGER_ID}-L" in text and f"{FINGER_ID}-R" in text
    left, right = sorted(solids, key=lambda s: s.Center().x)[::-1]
    stroke = Gripper().stroke_mm
    assert left.BoundingBox().xmin == pytest.approx(stroke, abs=1e-3), "the left finger's inner face, moved out by the stroke"
    assert right.BoundingBox().xmax == pytest.approx(-stroke, abs=1e-3)


def test_each_stl_is_one_watertight_finger_lying_on_the_bed(exported):
    for key in ("stl_left", "stl_right"):
        mesh = trimesh.load(exported.files[key])

        assert mesh.is_watertight and mesh.body_count == 1, key
        assert mesh.bounds[0][2] == pytest.approx(0, abs=1e-6), "on the bed"
        assert mesh.extents[0] == pytest.approx(Gripper().blade_mm[2], abs=0.01), "lying down: the finger's length runs along the bed"


def test_the_print_sheet_is_a_one_page_pdf(exported):
    pdf = exported.files["print_sheet"].read_bytes()

    assert pdf.startswith(b"%PDF")
    assert b"/Count 1" in pdf


def test_the_imprint_baseline_exports_but_the_stock_fingers_dont(cad, tmp_path):
    imprint = cad.export(CAP, Design(kind="imprint"), Gripper(), finger_id="EXP-0042-IMP", stem=tmp_path / "imp")

    assert imprint.blocked == [] and "print_sheet" not in imprint.files
    with pytest.raises(ValueError, match="stock"):
        cad.export(CAP, Design(kind="stock"), Gripper(), finger_id="EXP-0042-STOCK", stem=tmp_path / "stock")
    assert not list(tmp_path.glob("stock*"))


def test_without_a_font_the_files_are_still_written_and_the_check_says_why(cad, tmp_path, monkeypatch):
    def no_font(*args, **kwargs):
        raise AttributeError("'NoneType' object has no attribute 'FontName'")

    monkeypatch.setattr(finger_cad.cq.Compound, "makeText", no_font)
    export = cad.export(CAP, VPAD, Gripper(), finger_id=FINGER_ID, stem=tmp_path / "plain", sheet=sheet(sim_backend="isaac"))
    engraved = next(c for c in export.checks if c.name == "engraved id")

    assert all(path.exists() for path in export.files.values()) and len(export.files) == 4
    assert not engraved.ok and not engraved.blocking and "no font" in engraved.detail
    assert export.blocked == []


def test_a_blocking_failure_is_reported_and_the_files_are_still_written(cad, tmp_path):
    export = cad.export(CAP, VPAD, Gripper(max_finger_length_mm=50), finger_id=FINGER_ID, stem=tmp_path / "long")

    assert [c.name for c in export.blocked] == ["finger length"]
    assert export.files["step"].exists()
