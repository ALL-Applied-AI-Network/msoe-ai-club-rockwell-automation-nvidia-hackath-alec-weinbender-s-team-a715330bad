"""Nominal and true part poses: offsets live in the gripper frame at the grasp."""

import math

import pytest

from sim_server.models.offset import Offset
from sim_server.models.part import Part
from sim_server.robot.poses import DROP_GAP, NOMINAL_SITE_XY, gripper_axes, nominal_pose, true_pose, yaw_quaternion

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
