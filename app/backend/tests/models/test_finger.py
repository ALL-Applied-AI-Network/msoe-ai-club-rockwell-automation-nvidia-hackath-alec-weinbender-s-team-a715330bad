import numpy as np
import pytest

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.family import VPadParams
from api.models.finger import (
    BLADE_MM,
    SQUEEZE_MM,
    STROKE_MM,
    WALL_MM,
    build_finger,
    footprints,
    overlaps,
    problems,
    seat_distance,
    section,
    sections,
    stock_finger,
    stock_grasp_pose,
    v_profile,
)
from api.models.part import Part
from api.models.piece import hull_piece

CAP, CUBE = Part(), Part(shape="box")
FLAT = VPadParams(pad_width_mm=20, slack_mm=3, tip_height_mm=4)
CENTRED = {"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}


def vpad(**changes) -> Design:
    """FLAT with some parameters changed. model_copy skips validation, so impossible values can be tested too."""
    return Design(params=FLAT.model_copy(update=changes))


def box_piece(xs, ys, zs):
    return hull_piece([(x, y, z) for x in xs for y in ys for z in zs])


# A C-shaped part seen from above, opening toward +y: two walls along y joined at the -y end. Its bounding box is
# 20 x 20 x 10 mm, but the middle of its +y half is empty.
C_SHAPE = Part(
    shape="mesh",
    pieces=[
        box_piece((-10, -6), (-10, 10), (0, 10)),
        box_piece((6, 10), (-10, 10), (0, 10)),
        box_piece((-6, 6), (-10, -6), (0, 10)),
    ],
)


def volume(piece) -> float:
    """Signed volume from the faces: positive only if the triangles are closed and wound outward."""
    p = np.array(piece.points)
    return sum(np.dot(p[a], np.cross(p[b], p[c])) for a, b, c in piece.triangles) / 6


def test_part_extent_is_along_the_jaws_across_and_up():
    assert Part(diameter_mm=17, length_mm=140, axis="z").extent_mm == (17, 17, 140)
    assert Part(diameter_mm=17, length_mm=140, axis="y").extent_mm == (17, 140, 17)
    assert Part(diameter_mm=17, length_mm=140, axis="x").extent_mm == (140, 17, 17)
    assert Part(shape="box", width_mm=1, depth_mm=2, height_mm=3).extent_mm == (1, 2, 3)
    assert C_SHAPE.extent_mm == (20, 20, 10)
    assert CAP.round_from_above and not CUBE.round_from_above and not C_SHAPE.round_from_above


def test_a_flat_pad_is_one_strip_a_bridge_and_the_stock_blade_top():
    finger = build_finger(CAP, Design(params=FLAT))

    assert len(finger.pieces) == 3
    assert all(volume(piece) > 0 for piece in finger.pieces)
    assert max(z for piece in finger.pieces for *_, z in piece.points) == BLADE_MM[2]
    assert finger.jaw_close_mm == pytest.approx(STROKE_MM - FLAT.slack_mm - SQUEEZE_MM)
    assert finger.contact_mm == pytest.approx(CAP.extent_mm[2] - FLAT.tip_height_mm)
    assert problems(CAP, finger) == []


def test_a_groove_seats_a_round_part_deeper_so_the_jaws_close_further():
    grooved = build_finger(CAP, vpad(groove_angle_deg=90, groove_depth_mm=3))
    flat = build_finger(CAP, Design(params=FLAT))

    assert len(grooved.pieces) == 6
    assert grooved.jaw_close_mm < flat.jaw_close_mm
    assert problems(CAP, grooved) == []


def test_the_closed_gap_is_twice_the_pad_faces_x_with_the_jaws_closed():
    face = FLAT.slack_mm + CAP.diameter_mm / 2 - STROKE_MM

    assert build_finger(CAP, Design(params=FLAT)).closed_gap_mm == pytest.approx(2 * face)
    assert build_finger(CUBE, Design(params=FLAT)).closed_gap_mm == pytest.approx(2 * (FLAT.slack_mm + 5 - STROKE_MM))
    assert stock_finger(CUBE).closed_gap_mm == 0, "the stock blades meet when closed"


def test_the_gripper_moves_the_pad_and_the_grasp_settings():
    """A longer stroke leaves the pads closer together when closed (it still opens slack beyond the part), the jaws
    travel further to grip, and the grasp pose reports that stroke and TCP."""
    long = Gripper(stroke_mm=10.0, tcp_mm=300.0, pad_friction=(0.8, 0.7))
    default, longer = build_finger(CAP, Design(params=FLAT)), build_finger(CAP, Design(params=FLAT), long)

    assert longer.closed_gap_mm == pytest.approx(default.closed_gap_mm - 2 * (10 - STROKE_MM))
    assert longer.jaw_close_mm == pytest.approx(10 - FLAT.slack_mm - SQUEEZE_MM)
    assert longer.grasp_pose["jaw_open_mm"] == 10 and longer.grasp_pose["tcp_mm"] == 300
    assert longer.friction == (0.8, 0.7)
    assert problems(CAP, longer, long) == []
    assert "the jaws can't reach the gripping position" in problems(CAP, longer)[0], "the default stroke can't drive it"


def test_a_shorter_blade_or_a_longer_mount_leaves_less_room_for_a_tall_part():
    tall = Part(diameter_mm=17, length_mm=40)
    finger = build_finger(tall, vpad(tip_height_mm=2))

    assert problems(tall, finger) == []
    short = Gripper(blade_mm=(12.0, 6.0, 60.0), mount_kept_mm=30.0)
    assert "the part is too tall: the pad would have to reach into the mount" in problems(
        tall, build_finger(tall, vpad(tip_height_mm=2), short), short
    )


def test_v_profile_spans_the_pad_and_is_flat_at_180_degrees():
    assert v_profile(20, 180, 5) == [(-10, 0), (10, 0)]
    assert [y for y, _ in v_profile(20, 90, 3)] == pytest.approx([-10, -3, 0, 3, 10])
    assert v_profile(20, 90, 30)[1] == (0.0, 30)  # a mouth wider than the pad leaves no shoulders


def test_the_lead_in_cuts_back_the_pads_bottom_inner_edge():
    lead = 2.0
    finger = build_finger(CAP, vpad(lead_in_mm=lead))
    pad = finger.pieces[0]
    face = FLAT.slack_mm + CAP.diameter_mm / 2 - STROKE_MM

    bottom = section(pad, 1e-6)
    assert min(x for x, _ in bottom) == pytest.approx(face + lead, abs=1e-5)
    assert max(x for x, _ in bottom) - min(x for x, _ in bottom) == pytest.approx(WALL_MM, abs=1e-5), "a full wall stays behind the chamfer"
    assert min(x for x, _ in section(pad, lead + 1)) == pytest.approx(face)
    assert finger.contact_mm == pytest.approx(CAP.extent_mm[2] - FLAT.tip_height_mm - lead)


@pytest.mark.parametrize(
    "part",
    [CAP, CUBE, Part(diameter_mm=17, length_mm=140, axis="y"), Part(diameter_mm=17, length_mm=30, axis="x"), C_SHAPE],
    ids=["cap", "cube", "lying tube", "tube along the jaws", "C-shaped mesh"],
)
def test_the_imprint_baseline_fits_every_part_shape(part):
    finger = build_finger(part, Design(kind="imprint"))

    assert problems(part, finger) == []
    assert all(volume(piece) > 0 for piece in finger.pieces)


def test_a_meshs_imprint_is_the_notch_of_its_bounding_box():
    box = Part(shape="box", width_mm=20, depth_mm=20, height_mm=10)

    mesh_pieces = build_finger(C_SHAPE, Design(kind="imprint")).pieces
    box_pieces = build_finger(box, Design(kind="imprint")).pieces

    assert [p.points for p in mesh_pieces] == [p.points for p in box_pieces]


@pytest.mark.parametrize("design", [Design(kind="imprint"), vpad(groove_angle_deg=90, groove_depth_mm=3, lead_in_mm=2)])
def test_every_piece_fits_a_physx_convex_hull(design):
    """PhysX keeps at most 64 vertices per convex hull; a piece with more would be silently simplified in the sim."""
    assert all(len(piece.points) <= 64 for piece in build_finger(CAP, design).pieces)


def test_the_stock_fingers_can_grip_the_cube_but_not_open_around_the_cap():
    assert problems(CUBE, stock_finger(CUBE)) == []
    assert "with the jaws open, a finger would land on the centred part" in problems(CAP, stock_finger(CAP))
    with pytest.raises(ValueError):
        build_finger(CAP, Design(kind="stock"))


def test_the_stock_fingers_lead_in_comes_from_the_tip_gap():
    """The hooked tips open wider than the straight faces: (tip gap / 2 - stroke) of lead-in per side."""
    assert stock_finger(CUBE).contact_mm == pytest.approx(CUBE.height_mm - 2.5 - (16 / 2 - 6))
    assert stock_finger(CUBE, Gripper(stock_tip_gap_mm=12)).contact_mm == pytest.approx(CUBE.height_mm - 2.5)


def test_problems_catch_a_finger_that_lands_on_the_part():
    finger = build_finger(CAP, vpad(slack_mm=-1))

    assert "with the jaws open, a finger would land on the centred part" in problems(CAP, finger)


def test_problems_check_the_parts_clearance_when_given():
    """A flat pad 3 mm off the cube with a 3 mm wall needs 6 mm beside it along the jaws; its 20 mm width needs 5 mm
    either side across them."""
    finger = build_finger(CUBE, Design(params=FLAT))

    assert problems(CUBE, finger) == []
    assert problems(CUBE, finger, clearance_mm=6) == []
    assert problems(CUBE, finger, clearance_mm=5.5) == ["the finger needs 6.0 mm beside the part, and the part has 5.5 mm of clearance"]


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


def test_a_cylinder_lying_along_the_jaws_is_a_box_from_above():
    along = Part(diameter_mm=10, length_mm=10, axis="x")
    pad = [(5.5, -5), (8, -5), (8, 5), (5.5, 5)]

    for offset in (CENTRED, {"dx": 0, "dy": 0, "yaw_deg": 30}, {"dx": 1, "dy": 0, "yaw_deg": 0}):
        assert overlaps(pad, along, offset) == overlaps(pad, CUBE, offset)
    assert seat_distance(along, v_profile(20, 90, 3)) == seat_distance(CUBE, v_profile(20, 90, 3)) == 5 - 3


def test_a_meshs_outline_is_its_pieces_footprints():
    """A pad in the C's opening misses it, though it's inside the bounding box; shifting or turning the C brings a wall
    onto it."""
    pad = [(-2, 0), (2, 0), (2, 8), (-2, 8)]
    box = Part(shape="box", width_mm=20, depth_mm=20, height_mm=10)

    assert len(footprints(C_SHAPE)) == 3
    assert overlaps(pad, box, CENTRED)
    assert not overlaps(pad, C_SHAPE, CENTRED)
    assert overlaps(pad, C_SHAPE, {"dx": -5, "dy": 0, "yaw_deg": 0}), "the right wall moves onto the pad"
    assert overlaps(pad, C_SHAPE, {"dx": 0, "dy": 0, "yaw_deg": 90}), "turned a quarter, a wall crosses the opening"
    assert not overlaps(pad, C_SHAPE, {"dx": 0, "dy": -3, "yaw_deg": 0})
    assert overlaps(pad, C_SHAPE, CENTRED, margin=4.5), "within the margin of the walls at |x| = 6"


def test_a_v_pad_grips_a_mesh_by_its_bounding_box():
    finger = build_finger(C_SHAPE, Design(params=FLAT))

    assert finger.jaw_close_mm == pytest.approx(STROKE_MM - FLAT.slack_mm - SQUEEZE_MM)
    assert problems(C_SHAPE, finger) == []
    assert "with the jaws open, a finger would land on the centred part" in problems(C_SHAPE, build_finger(C_SHAPE, vpad(slack_mm=-1)))


def test_grasp_pose_keeps_the_calibrated_tcp():
    pose = build_finger(CAP, Design(params=FLAT)).grasp_pose

    assert pose["tcp_mm"] == 293 and pose["jaw_open_mm"] == STROKE_MM and pose["tip_height_mm"] == FLAT.tip_height_mm


def test_the_stock_grasp_pose_is_the_one_the_sim_runs():
    """The sim server's stock baseline grasps like the twin grasps its cubes: tips 2.5 mm up, each jaw closed 0.3 mm past
    where its hooked tip (2 mm outside the straight face) meets the part. For a 10 mm cube: 5 - 2 - 0.3 = 2.7 mm."""
    pose = stock_grasp_pose(Part(shape="box"))

    assert (pose["tip_height_mm"], pose["jaw_close_mm"], pose["jaw_open_mm"]) == (2.5, 2.7, 6.0)
    assert stock_grasp_pose(Part())["jaw_close_mm"] == 6.0  # the 31.75 mm cap is wider than the stock tips open: clamped
