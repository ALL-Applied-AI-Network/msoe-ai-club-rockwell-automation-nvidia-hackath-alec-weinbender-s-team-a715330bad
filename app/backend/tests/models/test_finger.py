import numpy as np
import pytest

from api.models.design import Design
from api.models.finger import (
    BLADE_MM,
    SQUEEZE_MM,
    STROKE_MM,
    WALL_MM,
    build_finger,
    overlaps,
    problems,
    section,
    sections,
    stock_finger,
    v_profile,
)
from api.models.part import Part

CAP, CUBE = Part(), Part(shape="box")
FLAT = {"pad_width_mm": 20, "groove_angle_deg": 180, "groove_depth_mm": 0, "slack_mm": 3, "tip_height_mm": 4, "lead_in_mm": 0}
CENTRED = {"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}


def volume(piece) -> float:
    """Signed volume from the faces: positive only if the triangles are closed and wound outward."""
    p = np.array(piece.points)
    return sum(np.dot(p[a], np.cross(p[b], p[c])) for a, b, c in piece.triangles) / 6


def test_part_extent_is_along_the_jaws_across_and_up():
    assert Part(diameter_mm=17, length_mm=140, upright=True).extent_mm == (17, 17, 140)
    assert Part(diameter_mm=17, length_mm=140, upright=False).extent_mm == (17, 140, 17)
    assert Part(shape="box", width_mm=1, depth_mm=2, height_mm=3).extent_mm == (1, 2, 3)
    assert CAP.round_from_above and not CUBE.round_from_above


def test_a_flat_pad_is_one_strip_a_bridge_and_the_stock_blade_top():
    finger = build_finger(CAP, Design(params=FLAT))

    assert len(finger.pieces) == 3
    assert all(volume(piece) > 0 for piece in finger.pieces)
    assert max(z for piece in finger.pieces for *_, z in piece.points) == BLADE_MM[2]
    assert finger.jaw_close_mm == pytest.approx(STROKE_MM - FLAT["slack_mm"] - SQUEEZE_MM)
    assert finger.contact_mm == pytest.approx(CAP.extent_mm[2] - FLAT["tip_height_mm"])
    assert problems(CAP, finger) == []


def test_a_groove_seats_a_round_part_deeper_so_the_jaws_close_further():
    grooved = build_finger(CAP, Design(params={**FLAT, "groove_angle_deg": 90, "groove_depth_mm": 3}))
    flat = build_finger(CAP, Design(params=FLAT))

    assert len(grooved.pieces) == 6
    assert grooved.jaw_close_mm < flat.jaw_close_mm
    assert problems(CAP, grooved) == []


def test_v_profile_spans_the_pad_and_is_flat_at_180_degrees():
    assert v_profile(20, 180, 5) == [(-10, 0), (10, 0)]
    assert [y for y, _ in v_profile(20, 90, 3)] == pytest.approx([-10, -3, 0, 3, 10])
    assert v_profile(20, 90, 30)[1] == (0.0, 30)  # a mouth wider than the pad leaves no shoulders


def test_the_lead_in_cuts_back_the_pads_bottom_inner_edge():
    lead = 2.0
    finger = build_finger(CAP, Design(params={**FLAT, "lead_in_mm": lead}))
    pad = finger.pieces[0]
    face = FLAT["slack_mm"] + CAP.diameter_mm / 2 - STROKE_MM

    bottom = section(pad, 1e-6)
    assert min(x for x, _ in bottom) == pytest.approx(face + lead, abs=1e-5)
    assert max(x for x, _ in bottom) - min(x for x, _ in bottom) == pytest.approx(WALL_MM, abs=1e-5), "a full wall stays behind the chamfer"
    assert min(x for x, _ in section(pad, lead + 1)) == pytest.approx(face)
    assert finger.contact_mm == pytest.approx(CAP.extent_mm[2] - FLAT["tip_height_mm"] - lead)


@pytest.mark.parametrize("part", [CAP, CUBE, Part(diameter_mm=17, length_mm=140, upright=False)], ids=["cap", "cube", "lying tube"])
def test_the_imprint_baseline_fits_every_part_shape(part):
    finger = build_finger(part, Design(kind="imprint"))

    assert problems(part, finger) == []
    assert all(volume(piece) > 0 for piece in finger.pieces)


@pytest.mark.parametrize(
    "design", [Design(kind="imprint"), Design(params={**FLAT, "groove_angle_deg": 90, "groove_depth_mm": 3, "lead_in_mm": 2})]
)
def test_every_piece_fits_a_physx_convex_hull(design):
    """PhysX keeps at most 64 vertices per convex hull; a piece with more would be silently simplified in the sim."""
    assert all(len(piece.points) <= 64 for piece in build_finger(CAP, design).pieces)


def test_the_stock_fingers_can_grip_the_cube_but_not_open_around_the_cap():
    assert problems(CUBE, stock_finger(CUBE)) == []
    assert "with the jaws open, a finger would land on the centred part" in problems(CAP, stock_finger(CAP))
    with pytest.raises(ValueError):
        build_finger(CAP, Design(kind="stock"))


def test_problems_catch_a_finger_that_lands_on_the_part():
    finger = build_finger(CAP, Design(params={**FLAT, "slack_mm": -1}))

    assert "with the jaws open, a finger would land on the centred part" in problems(CAP, finger)


def test_sections_mirror_the_finger_across_the_jaws():
    finger = build_finger(CAP, Design(params=FLAT))

    right, left = sections(finger, 1.0, STROKE_MM)[:2]

    assert min(x for x, _ in right) == pytest.approx(-max(x for x, _ in left))
    assert not overlaps(right, CAP, CENTRED)
    assert overlaps(right, CAP, {"dx": 6.0, "dy": 0.0})


def test_a_box_turned_by_its_yaw_can_reach_a_pad_it_clears_square():
    pad = [(5.5, -5), (8, -5), (8, 5), (5.5, 5)]

    assert not overlaps(pad, CUBE, CENTRED)
    assert overlaps(pad, CUBE, {"dx": 0, "dy": 0, "yaw_deg": 30})


def test_grasp_pose_keeps_the_calibrated_tcp():
    pose = build_finger(CAP, Design(params=FLAT)).grasp_pose

    assert pose["tcp_mm"] == 293 and pose["jaw_open_mm"] == STROKE_MM and pose["tip_height_mm"] == FLAT["tip_height_mm"]
