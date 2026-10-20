"""Nominal and true part poses (offsets live in the gripper frame at the grasp), and the in-hand pose read back."""

import math

import pytest

from sim_server.models.offset import Offset
from sim_server.models.part import Part
from sim_server.robot.poses import DROP_GAP, NOMINAL_SITE_XY, gripper_axes, in_hand_pose, nominal_pose, true_pose, yaw_quaternion

CUBE = Part(shape="box", size=(0.010, 0.010, 0.010), mass=0.004)
SURFACE = -0.0051


def test_gripper_axes_follow_g():
    (x, y) = gripper_axes((0.0, 1.0))
    assert x == pytest.approx((0.0, 1.0)) and y == pytest.approx((-1.0, 0.0))  # y = z cross x with z up
    (x, y) = gripper_axes((0.0, -2.0))
    assert x == pytest.approx((0.0, -1.0)) and y == pytest.approx((1.0, 0.0))


def test_nominal_pose_rests_on_the_surface_aligned_with_the_jaws():
    pose = nominal_pose(CUBE, (0.0, 1.0), SURFACE)
    assert pose.position == pytest.approx((*NOMINAL_SITE_XY, SURFACE + 0.005 + DROP_GAP))
    assert pose.yaw_deg == pytest.approx(90.0)  # part x (box_mm[0]) along the closing direction
    lying = Part(shape="cylinder", size=(0.010, 0.020, 0.010), mass=0.003, cylinder_axis="y")
    assert nominal_pose(lying, (1.0, 0.0), SURFACE).position[2] == pytest.approx(SURFACE + 0.005 + DROP_GAP)
    along = Part(shape="cylinder", size=(0.020, 0.010, 0.010), mass=0.003, cylinder_axis="x")
    assert nominal_pose(along, (1.0, 0.0), SURFACE).position[2] == pytest.approx(SURFACE + 0.005 + DROP_GAP)


@pytest.mark.parametrize("spread", [(0.0, 1.0), (0.0, -1.0), (1.0, 0.0)])
def test_true_pose_moves_in_the_gripper_frame(spread):
    nominal = nominal_pose(CUBE, spread, SURFACE)
    moved = true_pose(nominal, spread, Offset(dx=0.002, dy=0.0, yaw_deg=0.0))  # +dx: toward JawL, i.e. along the spread direction
    delta = [m - n for m, n in zip(moved.position, nominal.position, strict=True)]
    assert delta == pytest.approx([0.002 * spread[0], 0.002 * spread[1], 0.0])
    across = true_pose(nominal, spread, Offset(dx=0.0, dy=0.001, yaw_deg=0.0))
    (_, (yx, yy)) = gripper_axes(spread)
    assert [a - n for a, n in zip(across.position, nominal.position, strict=True)] == pytest.approx([0.001 * yx, 0.001 * yy, 0.0])
    turned = true_pose(nominal, spread, Offset(dx=0.0, dy=0.0, yaw_deg=12.5))
    assert turned.position == nominal.position and turned.yaw_deg == pytest.approx(nominal.yaw_deg + 12.5)


def test_yaw_quaternion_is_scalar_first_about_z():
    assert yaw_quaternion(0.0) == pytest.approx((1.0, 0.0, 0.0, 0.0))
    w, x, y, z = yaw_quaternion(90.0)
    assert (w, x, y, z) == pytest.approx((math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)))
    assert w * w + z * z == pytest.approx(1.0)


# ------------------------------------------------------------------ in-hand pose

GRIP = (0.30, 0.0, 0.1274)  # a commanded fingertip point at the end of the lift
EXPECTED_Z = 0.0025  # a 10 mm cube with tips 2.5 mm up: its centre 2.5 mm above G's origin


def axis_angle(axis, deg):
    """A unit quaternion (w, x, y, z) for a turn about a unit axis."""
    half = math.radians(deg) / 2
    return (math.cos(half), *(math.sin(half) * a for a in axis))


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def placed(spread, dx=0.0, dy=0.0, dz=0.0, turn=(1.0, 0.0, 0.0, 0.0)):
    """A part at (dx, dy, dz) from the centred position in G, with its nominal yaw (x along the spread) then `turn`
    applied in the world frame."""
    (xx, xy), (yx, yy) = gripper_axes(spread)
    position = (GRIP[0] + dx * xx + dy * yx, GRIP[1] + dx * xy + dy * yy, GRIP[2] + EXPECTED_Z + dz)
    return position, qmul(turn, yaw_quaternion(math.degrees(math.atan2(spread[1], spread[0]))))


def reading(pose):
    return (pose.dx, pose.dy, pose.dz, pose.tilt_deg, pose.yaw_deg)


@pytest.mark.parametrize("spread", [(0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (0.6, -0.8)])
def test_a_centred_part_reads_zero(spread):
    assert reading(in_hand_pose(*placed(spread), GRIP, spread, EXPECTED_Z)) == pytest.approx((0, 0, 0, 0, 0), abs=1e-9)


@pytest.mark.parametrize("spread", [(0.0, 1.0), (0.0, -1.0), (0.6, -0.8)])
def test_offsets_read_back_in_the_gripper_frame(spread):
    """dx toward JawL, dy along G's y = z x x, dz up, whatever way the jaws point in the base frame."""
    pose = in_hand_pose(*placed(spread, dx=0.0012, dy=-0.0021, dz=0.0004), GRIP, spread, EXPECTED_Z)
    assert reading(pose) == pytest.approx((0.0012, -0.0021, 0.0004, 0.0, 0.0), abs=1e-9)


def test_a_true_pose_offset_reads_back_as_itself():
    """true_pose and in_hand_pose agree on G: a part lifted exactly as it was placed reads its camera-error offset."""
    spread = (0.0, -1.0)
    nominal = nominal_pose(CUBE, spread, SURFACE)
    moved = true_pose(nominal, spread, Offset(dx=0.001, dy=0.002, yaw_deg=-7.5))
    lifted = (moved.position[0], moved.position[1], moved.position[2] + 0.13)
    grip = (*NOMINAL_SITE_XY, SURFACE + 0.0025 + 0.13)
    pose = in_hand_pose(lifted, yaw_quaternion(moved.yaw_deg), grip, spread, expected_z=0.005 - 0.0025)
    assert reading(pose) == pytest.approx((0.001, 0.002, DROP_GAP, 0.0, -7.5), abs=1e-9)


@pytest.mark.parametrize(
    ("turn_deg", "yaw"), [(30.0, 30.0), (-45.0, -45.0), (180.0, 180.0), (-180.0, 180.0), (190.0, -170.0), (-190.0, 170.0)]
)
def test_yaw_is_the_turn_about_g_z_wrapped(turn_deg, yaw):
    spread = (0.0, 1.0)
    pose = in_hand_pose(*placed(spread, turn=axis_angle((0, 0, 1), turn_deg)), GRIP, spread, EXPECTED_Z)
    assert pose.yaw_deg == pytest.approx(yaw) and -180.0 < pose.yaw_deg <= 180.0
    assert pose.tilt_deg == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("axis", [(1, 0, 0), (0, 1, 0), (0.6, 0.8, 0)])
def test_tilt_is_the_angle_from_vertical_about_any_horizontal_axis(axis):
    spread = (0.0, 1.0)
    pose = in_hand_pose(*placed(spread, turn=axis_angle(axis, 12.0)), GRIP, spread, EXPECTED_Z)
    assert pose.tilt_deg == pytest.approx(12.0)
    assert abs(pose.yaw_deg) < 2.0  # tilting barely turns the projected x axis


def test_tilt_about_g_x_keeps_the_yaw():
    spread = (0.0, 1.0)  # G's x is base +Y
    pose = in_hand_pose(*placed(spread, turn=axis_angle((0, 1, 0), 20.0)), GRIP, spread, EXPECTED_Z)
    assert (pose.tilt_deg, pose.yaw_deg) == pytest.approx((20.0, 0.0), abs=1e-9)


def test_quaternion_scale_and_sign_dont_matter():
    spread = (0.6, -0.8)
    position, q = placed(spread, dx=0.001, turn=qmul(axis_angle((0, 0, 1), 25.0), axis_angle((1, 0, 0), 5.0)))
    expected = reading(in_hand_pose(position, q, GRIP, spread, EXPECTED_Z))
    assert reading(in_hand_pose(position, tuple(-3 * v for v in q), GRIP, spread, EXPECTED_Z)) == pytest.approx(expected)


def test_the_frame_only_needs_to_be_shared():
    """World = base + a translation, so moving the part and G together changes nothing."""
    spread = (0.0, 1.0)
    position, q = placed(spread, dx=0.002, dy=0.001, turn=axis_angle((0, 0, 1), 10.0))
    shift = (4.0, -2.0, 0.9)
    world = in_hand_pose(
        [p + s for p, s in zip(position, shift, strict=True)], q, [g + s for g, s in zip(GRIP, shift, strict=True)], spread, EXPECTED_Z
    )
    assert reading(world) == pytest.approx(reading(in_hand_pose(position, q, GRIP, spread, EXPECTED_Z)))


# Cylinders. With the jaws along base +Y (spread (0, 1)), G's x is base +Y and G's y is base -X, so a lying cylinder's
# axis starts along base X ("y", across the jaws) or base Y ("x", along them).
OWN_AXIS = {"y": (1, 0, 0), "x": (0, 1, 0), "z": (0, 0, 1)}  # each cylinder axis's line in the base frame, nominal pose
RAISE_ABOUT = {"y": (0, 1, 0), "x": (1, 0, 0)}  # a turn about this horizontal line lifts that axis out of G's xy plane


@pytest.mark.parametrize("cylinder_axis", ["y", "x", "z"])
@pytest.mark.parametrize("roll_deg", [35.0, -70.0, 180.0])
def test_a_cylinder_rolling_about_its_own_axis_reads_zero(cylinder_axis, roll_deg):
    """The lying cylinder rolled 9..92 degrees in the jaws on Brev (2026-10-20) and read it all as tilt."""
    spread = (0.0, 1.0)
    position, q = placed(spread, turn=axis_angle(OWN_AXIS[cylinder_axis], roll_deg))
    pose = in_hand_pose(position, q, GRIP, spread, EXPECTED_Z, cylinder_axis=cylinder_axis)
    assert (pose.tilt_deg, pose.yaw_deg) == pytest.approx((0.0, 0.0), abs=1e-9)


@pytest.mark.parametrize("cylinder_axis", ["y", "x"])
def test_a_lying_cylinder_tilts_when_its_axis_leaves_the_horizontal(cylinder_axis):
    spread = (0.0, 1.0)
    roll_then_raise = qmul(axis_angle(RAISE_ABOUT[cylinder_axis], 10.0), axis_angle(OWN_AXIS[cylinder_axis], 50.0))
    pose = in_hand_pose(*placed(spread, turn=roll_then_raise), GRIP, spread, EXPECTED_Z, cylinder_axis=cylinder_axis)
    assert (pose.tilt_deg, pose.yaw_deg) == pytest.approx((10.0, 0.0), abs=1e-9)


@pytest.mark.parametrize("cylinder_axis", ["y", "x"])
@pytest.mark.parametrize(("turn_deg", "yaw"), [(15.0, 15.0), (-30.0, -30.0), (170.0, -10.0), (-100.0, 80.0), (90.0, 90.0), (-90.0, 90.0)])
def test_a_lying_cylinder_yaw_is_its_axis_turning_about_g_z_with_both_ends_alike(cylinder_axis, turn_deg, yaw):
    spread = (0.0, 1.0)
    pose = in_hand_pose(*placed(spread, turn=axis_angle((0, 0, 1), turn_deg)), GRIP, spread, EXPECTED_Z, cylinder_axis=cylinder_axis)
    assert pose.yaw_deg == pytest.approx(yaw) and -90.0 < pose.yaw_deg <= 90.0
    assert pose.tilt_deg == pytest.approx(0.0, abs=1e-9)


def test_a_standing_cylinder_reads_its_lean_and_no_yaw():
    spread = (0.6, -0.8)
    lean = qmul(axis_angle((0.8, 0.6, 0), 12.0), axis_angle((0, 0, 1), 40.0))  # turned about its axis, then leaning
    pose = in_hand_pose(*placed(spread, dx=0.001, turn=lean), GRIP, spread, EXPECTED_Z, cylinder_axis="z")
    assert reading(pose) == pytest.approx((0.001, 0.0, 0.0, 12.0, 0.0), abs=1e-9)


def test_a_box_keeps_the_turn_a_cylinder_would_ignore():
    spread = (0.0, 1.0)
    pose = in_hand_pose(*placed(spread, turn=axis_angle(OWN_AXIS["y"], 35.0)), GRIP, spread, EXPECTED_Z)
    assert pose.tilt_deg == pytest.approx(35.0)


@pytest.mark.parametrize("q", [(0.0, 0.0, 0.0, 0.0), (float("nan"), 0.0, 0.0, 1.0)])
def test_a_bad_quaternion_is_refused(q):
    with pytest.raises(ValueError):
        in_hand_pose(GRIP, q, GRIP, (0.0, 1.0), EXPECTED_Z)
