"""Unit conversion, design validation, the stock grasp rule, and packing grasps into environments."""

import pytest
import scene_config as C

from sim_server.models.finger import FingerDesign
from sim_server.models.grasp import GraspSettings
from sim_server.models.part import Part
from sim_server.models.pose import InHandPose
from sim_server.services.batches import (
    chunk_grasps,
    design_from_mm,
    design_warnings,
    grasp_settings,
    in_hand_to_mm,
    offset_from_mm,
    part_from_mm,
    stock_fits,
)

MM = 1e-3
CUBE = Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)


def test_parts_convert_to_metres_and_kilograms():
    upright = part_from_mm("cylinder", diameter_mm=31.75, length_mm=15.7, upright=True, mass_g=5)
    assert upright.size == pytest.approx((0.03175, 0.03175, 0.0157)) and upright.cylinder_axis == "z"
    assert upright.mass == pytest.approx(0.005) and upright.friction is None
    lying = part_from_mm("cylinder", diameter_mm=10, length_mm=20, upright=False, mass_g=3)
    assert lying.size == pytest.approx((0.010, 0.020, 0.010)) and lying.cylinder_axis == "y"  # axis across the jaws
    assert lying.width == pytest.approx(0.010) and lying.height == pytest.approx(0.010)
    box = part_from_mm("box", box_mm=[10, 12, 8], mass_g=4, friction=[0.4, 0.3])
    assert box.size == pytest.approx((0.010, 0.012, 0.008)) and box.cylinder_axis is None
    assert box.friction == (0.4, 0.3)


def test_cylinder_axis_wins_over_the_legacy_upright_flag():
    along = part_from_mm("cylinder", diameter_mm=10, length_mm=20, axis="x", mass_g=3)
    assert along.size == pytest.approx((0.020, 0.010, 0.010)) and along.cylinder_axis == "x"  # the jaws grip its end faces
    assert along.width == pytest.approx(0.020) and along.length == pytest.approx(0.020) and along.diameter == pytest.approx(0.010)
    assert part_from_mm("cylinder", diameter_mm=10, length_mm=20, axis="z", upright=False, mass_g=3).cylinder_axis == "z"
    assert part_from_mm("cylinder", diameter_mm=10, length_mm=20, axis="y", upright=True, mass_g=3).cylinder_axis == "y"
    assert part_from_mm("cylinder", diameter_mm=10, length_mm=20, mass_g=3).cylinder_axis == "z"  # neither: standing


def test_mesh_parts_are_recentred_to_mid_height(box_piece):
    """An L-bracket in the grasp frame: a leg over the grasp centre and a foot off to -y, on the table."""
    leg, foot = box_piece(-5, 5, -2, 2, 0, 24), box_piece(-5, 5, -18, -2, 0, 4)
    bracket = part_from_mm("mesh", pieces_mm=[leg, foot], mass_g=4.3, friction=[0.45, 0.35])
    assert bracket.shape == "mesh" and len(bracket.pieces) == 2
    assert bracket.size == pytest.approx((0.010, 0.020, 0.024))  # extent along x, y, and the height
    assert bracket.width == pytest.approx(0.010) and bracket.height == pytest.approx(0.024)
    zs = [z for piece in bracket.pieces for _, _, z in piece.points]
    assert (min(zs), max(zs)) == pytest.approx((-0.012, 0.012))  # origin at mid-height above the grasp centre
    ys = [y for piece in bracket.pieces for _, y, _ in piece.points]
    assert (min(ys), max(ys)) == pytest.approx((-0.018, 0.002))  # x and y stay put: the grasp centre is the origin
    assert bracket.pieces[0].triangles == tuple(tuple(t) for t in leg[1])
    assert bracket.friction == (0.45, 0.35) and bracket.mass == pytest.approx(0.0043)


def test_mesh_parts_are_validated_like_finger_pieces(box_piece):
    points, triangles = box_piece(-5, 5, -5, 5, 0, 10)
    with pytest.raises(ValueError, match="indexes"):
        part_from_mm("mesh", pieces_mm=[(points, [*triangles, (0, 1, 8)])], mass_g=4)
    flat = [(x, y, 0.0) for x, y, _ in points]
    with pytest.raises(ValueError, match="zero volume"):
        part_from_mm("mesh", pieces_mm=[(flat, triangles)], mass_g=4)
    with pytest.raises(ValueError, match="below the table"):
        part_from_mm("mesh", pieces_mm=[box_piece(-5, 5, -5, 5, -1, 10)], mass_g=4)
    with pytest.raises(ValueError, match="pieces"):
        part_from_mm("mesh", pieces_mm=[], mass_g=4)
    with pytest.raises(ValueError, match="pieces"):
        part_from_mm("mesh", mass_g=4)
    rounded = part_from_mm("mesh", pieces_mm=[box_piece(-5, 5, -5, 5, -1e-4, 10)], mass_g=4)  # rounding below z = 0 is fine
    assert rounded.height == pytest.approx(0.010)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shape": "cylinder", "mass_g": 5, "diameter_mm": 10},
        {"shape": "cylinder", "mass_g": 5, "diameter_mm": 10, "length_mm": 20, "axis": "w"},
        {"shape": "box", "mass_g": 5},
        {"shape": "box", "mass_g": 5, "box_mm": [10, 0, 10]},
        {"shape": "sphere", "mass_g": 5, "diameter_mm": 10},
        {"shape": "box", "mass_g": 0, "box_mm": [10, 10, 10]},
    ],
)
def test_bad_parts_are_rejected(kwargs):
    shape = kwargs.pop("shape")
    with pytest.raises(ValueError):
        part_from_mm(shape, **kwargs)


def test_custom_design_converts_pieces_to_metres(box_piece):
    points, triangles = box_piece(0, 12, -3, 3, 0, 76)
    design = design_from_mm("t3", pieces_mm=[(points, triangles)], friction=[0.6, 0.5], tip_height_mm=4.0, jaw_close_mm=1.2)
    assert not design.is_stock
    assert design.pieces[0].points[-1] == pytest.approx((0.012, 0.003, 0.076))
    assert design.friction == (0.6, 0.5)
    assert design.tip_height == pytest.approx(0.004) and design.jaw_close == pytest.approx(0.0012)
    assert design.finger_key == (design.pieces, design.friction)


def test_stock_design():
    design = design_from_mm("stock")
    assert design.is_stock and design.finger_key is None and design.tip_height is None


def test_design_validation(box_piece):
    points, triangles = box_piece(0, 12, -3, 3, 0, 76)
    with pytest.raises(ValueError, match="friction"):
        design_from_mm("stock", friction=[0.5, 0.4])
    with pytest.raises(ValueError, match="need"):
        design_from_mm("t", pieces_mm=[(points, triangles)], friction=[0.5, 0.4], tip_height_mm=2)
    with pytest.raises(ValueError, match="indexes"):
        design_from_mm("t", pieces_mm=[(points, [*triangles, (0, 1, 8)])], friction=[0.5, 0.4], tip_height_mm=2, jaw_close_mm=1)
    flat = [(x, y, 0.0) for x, y, _ in points]
    with pytest.raises(ValueError, match="zero volume"):
        design_from_mm("t", pieces_mm=[(flat, triangles)], friction=[0.5, 0.4], tip_height_mm=2, jaw_close_mm=1)
    with pytest.raises(ValueError, match="empty"):
        design_from_mm("t", pieces_mm=[], friction=[0.5, 0.4], tip_height_mm=2, jaw_close_mm=1)


def test_stock_rule_reproduces_the_twin_cube_grasp(geo):
    cube = part_from_mm("box", box_mm=[10, 10, 10], mass_g=4)
    settings = grasp_settings(FingerDesign(id="stock"), cube, geo)
    assert settings.tip_height == pytest.approx(C.CUBE_TIP_CLEARANCE)
    assert settings.jaw_close == pytest.approx(C.CUBE_JAW_HALF_TARGET)


def test_stock_rule_generalises_to_other_widths(geo):
    wide = Part(shape="box", size=(0.020, 0.010, 0.010), mass=0.004)
    assert grasp_settings(FingerDesign(id="stock"), wide, geo).jaw_close == pytest.approx(geo.jaw_open)  # clamped to the stroke
    thin = Part(shape="box", size=(0.003, 0.010, 0.010), mass=0.004)
    assert grasp_settings(FingerDesign(id="stock"), thin, geo).jaw_close == pytest.approx(geo.jaw_closed)
    cylinder = part_from_mm("cylinder", diameter_mm=12, length_mm=20, upright=True, mass_g=3)
    assert grasp_settings(FingerDesign(id="stock"), cylinder, geo).jaw_close == pytest.approx(0.006 - geo.finger_inner_tip - 0.0003)
    override = FingerDesign(id="stock", tip_height=0.004, jaw_close=0.001)
    assert grasp_settings(override, cylinder, geo) == GraspSettings(tip_height=0.004, jaw_close=0.001)


def test_custom_settings_come_from_the_design():
    design = FingerDesign(id="t", pieces=(), friction=(0.6, 0.5), tip_height=0.004, jaw_close=0.0012)
    assert grasp_settings(design, CUBE, None) == GraspSettings(tip_height=0.004, jaw_close=0.0012)


def test_stock_fits(geo, box_piece):
    assert stock_fits(part_from_mm("box", box_mm=[10, 10, 10], mass_g=4), geo)
    assert not stock_fits(part_from_mm("cylinder", diameter_mm=31.75, length_mm=15.7, mass_g=5), geo)  # the vial cap
    assert not stock_fits(part_from_mm("cylinder", diameter_mm=10, length_mm=20, axis="x", mass_g=3), geo)  # 20 mm along the jaws
    assert stock_fits(part_from_mm("mesh", pieces_mm=[box_piece(-5, 5, -20, 20, 0, 5)], mass_g=4), geo)  # 10 mm wide, 40 deep
    assert not stock_fits(part_from_mm("mesh", pieces_mm=[box_piece(-2, 15, -2, 2, 0, 5)], mass_g=4), geo)  # 17 mm wide


def test_design_warnings(box_piece):
    points, triangles = box_piece(-1, 12, -3, 3, -2, 76)  # crosses the centre plane and reaches below the tip plane
    design = design_from_mm("t", pieces_mm=[(points, triangles)], friction=[0.6, 0.5], tip_height_mm=1.0, jaw_close_mm=0.5)
    warnings = design_warnings(design, grasp_settings(design, CUBE, None))
    assert len(warnings) == 2
    assert "work surface" in warnings[0] and "meet" in warnings[1]
    assert design_warnings(FingerDesign(id="stock"), GraspSettings(tip_height=0.0025, jaw_close=0.0027)) == []


def test_offsets_convert_to_metres():
    offset = offset_from_mm(1.5, -2.0, 10.0)
    assert (offset.dx, offset.dy, offset.yaw_deg) == pytest.approx((0.0015, -0.002, 10.0))


def test_in_hand_poses_convert_back_to_millimetres():
    pose = InHandPose(dx=0.0012345678, dy=-0.0005, dz=-1e-9, tilt_deg=1.23456789, yaw_deg=-179.99999)
    assert in_hand_to_mm(pose) == [1.2346, -0.5, 0.0, 1.2346, 180.0]  # yaw rounds to -180, which wraps to 180
    assert str(in_hand_to_mm(pose)[2]) == "0.0"  # no -0.0 in the response
    assert in_hand_to_mm(None) is None


def test_chunks_keep_design_major_order():
    pairs = [(d, o) for d in range(3) for o in range(81)]
    chunks = chunk_grasps(pairs, 100)
    assert [len(c) for c in chunks] == [100, 100, 43]
    assert [p for c in chunks for p in c] == pairs
    assert chunks[0][80:82] == [(0, 80), (1, 0)]  # each design's copies are contiguous
    assert chunk_grasps(pairs[:3], 1) == [[(0, 0)], [(0, 1)], [(0, 2)]]  # the reference path: one grasp per chunk
    assert chunk_grasps([], 4) == []
    with pytest.raises(ValueError):
        chunk_grasps(pairs, 0)
