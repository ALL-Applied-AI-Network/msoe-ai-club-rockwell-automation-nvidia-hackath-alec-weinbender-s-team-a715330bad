"""Unit conversion, design validation, the stock grasp rule, and packing grasps into environments."""

import pytest
import scene_config as C

from sim_server.models.finger import FingerDesign
from sim_server.models.grasp import GraspSettings
from sim_server.models.part import Part
from sim_server.services.batches import (
    chunk_grasps,
    design_from_mm,
    design_warnings,
    grasp_settings,
    offset_from_mm,
    part_from_mm,
    stock_fits,
)

MM = 1e-3
CUBE = Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)


def test_parts_convert_to_metres_and_kilograms():
    upright = part_from_mm("cylinder", diameter_mm=31.75, length_mm=15.7, upright=True, mass_g=5)
    assert upright.size == pytest.approx((0.03175, 0.03175, 0.0157)) and upright.cylinder_axis == "z"
    assert upright.mass == pytest.approx(0.005)
    lying = part_from_mm("cylinder", diameter_mm=10, length_mm=20, upright=False, mass_g=3)
    assert lying.size == pytest.approx((0.010, 0.020, 0.010)) and lying.cylinder_axis == "y"  # axis across the jaws
    assert lying.width == pytest.approx(0.010) and lying.height == pytest.approx(0.010)
    box = part_from_mm("box", box_mm=[10, 12, 8], mass_g=4)
    assert box.size == pytest.approx((0.010, 0.012, 0.008)) and box.cylinder_axis is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shape": "cylinder", "mass_g": 5, "diameter_mm": 10},
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


def test_stock_fits(geo):
    assert stock_fits(part_from_mm("box", box_mm=[10, 10, 10], mass_g=4), geo)
    assert not stock_fits(part_from_mm("cylinder", diameter_mm=31.75, length_mm=15.7, mass_g=5), geo)  # the vial cap


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
