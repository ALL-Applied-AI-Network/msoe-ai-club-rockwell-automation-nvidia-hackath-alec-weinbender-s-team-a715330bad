"""The gripper frame G against the twin's own geometry (scene_config, gripper_geometry, and cell.py's placement formulas)."""

import gripper_geometry
import pytest
import scene_config as C

from sim_server.robot.gripper_frame import (
    finger_points_g,
    flange_from_g,
    g_from_flange,
    jaw_body_origin_flange,
    jaw_body_points,
    jaw_body_triangles,
    mirror,
    stock_profile_g,
)
from sim_server.services.batches import piece_volume

MM = 1e-3
SAMPLE_POINTS = [(0.0, 0.0, 0.0), (0.012, -0.003, 0.076), (0.004, 0.0025, 0.03), (-0.002, 0.001, -0.001)]


def close(a, b, tol=1e-12):
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def test_layout_matches_the_twin_tcp(geo):
    assert geo.carriage_x == pytest.approx(0.217)
    assert geo.finger_x == pytest.approx(geo.carriage_x)  # the custom blade starts at the SMC body's front (CARRIAGE_OVERLAP)
    assert geo.tip_offset == pytest.approx(C.TOOL_LENGTH) == pytest.approx(0.293)


def test_stock_blade_bounding_box_is_as_assumed(geo):
    profile = stock_profile_g(gripper_geometry.finger_profile(), geo)
    xs, zs = [x for x, _ in profile], [z for _, z in profile]
    assert (min(xs), max(xs)) == pytest.approx((0.0, 12 * MM))
    assert (min(zs), max(zs)) == pytest.approx((0.0, 76 * MM))
    assert geo.finger_thick / 2 == pytest.approx(3 * MM)  # extruded +-3 mm about y = 0


def test_stock_blade_hook_scallop_and_bevel(geo):
    profile = stock_profile_g(gripper_geometry.finger_profile(), geo)
    tip_face = sorted(x for x, z in profile if abs(z) < 1e-12)
    assert tip_face == pytest.approx([geo.finger_inner_tip, C.FINGER_TIP_WIDTH])  # hook tip face spans x 2.0 .. 7.5 mm
    assert geo.finger_inner_tip == pytest.approx(1.995 * MM, abs=1e-6)
    inner_face = sorted(z for x, z in profile if abs(x) < 1e-12)
    assert inner_face == pytest.approx([C.FINGER_LENGTH * (1 - C.SCALLOP_AT) + C.SCALLOP_R, 76 * MM])  # x = 0 only above 14.22 mm
    assert inner_face[0] == pytest.approx(14.22 * MM)
    assert any(x == pytest.approx(12 * MM) and z == pytest.approx(14 * MM) for x, z in profile)  # the outer bevel ends at (12, 14)
    assert any(x == pytest.approx(C.FINGER_TIP_WIDTH) and z == pytest.approx(0.0) for x, z in profile)  # and starts at (7.5, 0)


def test_tip_gap_closed_and_open(geo):
    hook = [(geo.finger_inner_tip, 0.0, 0.0)]
    for jaw, gap in ((geo.jaw_closed, 4 * MM), (geo.jaw_open, 16 * MM)):
        (left,), (right,) = finger_points_g(hook, +1, jaw), finger_points_g(hook, -1, jaw)
        assert left[0] - right[0] == pytest.approx(gap, abs=0.02 * MM)
    assert geo.open_tip_gap == pytest.approx(16 * MM, abs=0.02 * MM)


def test_g_axes_in_the_flange_frame(geo):
    origin = flange_from_g((0, 0, 0), geo)
    assert close(origin, (geo.tip_offset, 0, 0))
    axes = [tuple(a - o for a, o in zip(flange_from_g(e, geo), origin, strict=True)) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))]
    assert axes == [(0, 1, 0), (0, 0, -1), (-1, 0, 0)]  # x: spread toward JawL, y: -Z, z: back toward the wrist
    (a, b, c), (d, e, f), (g, h, i) = axes
    assert a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g) == 1  # right-handed
    for p in SAMPLE_POINTS:
        assert close(g_from_flange(flange_from_g(p, geo), geo), p)


@pytest.mark.parametrize("side", [+1, -1])
@pytest.mark.parametrize("jaw", [0.0, 0.0027, 0.006])
def test_jaw_body_points_ride_with_the_jaw(geo, side, jaw):
    """flange(finger in G at this opening) == jaw body origin (cell.py) + the point in the jaw body's frame."""
    origin = jaw_body_origin_flange(side, jaw, geo)
    for g_point, body_point in zip(finger_points_g(SAMPLE_POINTS, side, jaw), jaw_body_points(SAMPLE_POINTS, side, geo), strict=True):
        assert close(flange_from_g(g_point, geo), tuple(o + b for o, b in zip(origin, body_point, strict=True)), 1e-15)


@pytest.mark.parametrize("side", [+1, -1])
def test_stock_blade_lands_where_cell_py_puts_its_prisms(geo, side):
    """cell.attach_gripper: prism points (u, sign*v, z) translated by (finger_x - carriage_x, -sign*W/2, 0) in the jaw body.
    The same blade drawn in G (x = v, y = -z, z = L - u) must map to exactly those points."""
    for u, v in gripper_geometry.finger_profile():
        for z in (-geo.finger_thick / 2, geo.finger_thick / 2):
            twin = (geo.finger_x - geo.carriage_x + u, side * v - side * geo.finger_width / 2, z)
            (ours,) = jaw_body_points([(v, -z, geo.finger_length - u)], side, geo)
            assert close(ours, twin, 1e-15)


def test_mirror_keeps_pieces_outward(geo, box_piece):
    points_mm, triangles = box_piece(0, 12, -3, 3, 0, 76)
    points = [tuple(v * MM for v in p) for p in points_mm]
    assert piece_volume(points, triangles) > 0
    for side in (+1, -1):
        body = jaw_body_points(points, side, geo)
        assert piece_volume(body, jaw_body_triangles(triangles, side)) == pytest.approx(piece_volume(points, triangles))
    assert mirror((1.0, 2.0, 3.0)) == (-1.0, 2.0, 3.0)
