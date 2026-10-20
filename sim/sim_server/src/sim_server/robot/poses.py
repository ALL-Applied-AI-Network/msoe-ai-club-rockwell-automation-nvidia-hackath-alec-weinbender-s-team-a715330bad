"""Where the part is placed for each grasp: the nominal pose the robot plans for, and the true pose with camera error.

Isaac-free. Poses are in the robot base frame, the twin's planning frame: origin on the base mounting face, +X away from
the robot, +Y to its left, +Z up; the work surface is at z = SURFACE_DZ. World = base + (0, 0, TABLE_TOP_Z) + the
environment's origin.

The nominal grasp site is (0.30, 0.0), straight below the twin's home pose (fingertips at (0.30, 0, 0.24)), so the
approach is a vertical move and the arm is well inside its reach (the twin's cube picks span x 0.24..0.46). The jaws
close along base Y there, as for the twin's tower placements. The part's own frame has x along the closing direction
(toward JawL), y across it and z up, so a box's box_mm and a lying cylinder's axis line up with the jaws at the nominal pose.

The true pose (camera-error model) shifts and turns the part in the gripper's frame at the grasp. Only the world is set
up from it; the robot always plans at the nominal pose (the twin's rule: ground truth never feeds grasp commands).
"""

import math

from sim_server.models.offset import Offset
from sim_server.models.part import Part
from sim_server.models.pose import PartPose

NOMINAL_SITE_XY = (0.30, 0.0)
NOMINAL_SPREAD_XY = (0.0, 1.0)  # GraspPlanner flips it to whichever sign the wrist is already at
DROP_GAP = 1e-4  # spawn this far above the surface so the first step doesn't start in contact


def gripper_axes(spread_xy: tuple[float, float]) -> tuple[tuple[float, float], tuple[float, float]]:
    """The gripper frame's horizontal axes at a top-down grasp, in base XY: x along the closing direction toward JawL,
    y = z x x (z points up, back toward the wrist)."""
    norm = math.hypot(*spread_xy)
    sx, sy = spread_xy[0] / norm, spread_xy[1] / norm
    return (sx, sy), (-sy, sx)


def nominal_pose(part: Part, spread_xy: tuple[float, float], surface_z: float, site_xy=NOMINAL_SITE_XY) -> PartPose:
    """Resting on the surface at the site, its x axis along the closing direction."""
    (sx, sy), _ = gripper_axes(spread_xy)
    return PartPose(position=(site_xy[0], site_xy[1], surface_z + part.height / 2 + DROP_GAP), yaw_deg=math.degrees(math.atan2(sy, sx)))


def true_pose(nominal: PartPose, spread_xy: tuple[float, float], offset: Offset) -> PartPose:
    """The nominal pose moved by (dx, dy) in the gripper frame and turned by yaw about its own vertical axis."""
    (xx, xy), (yx, yy) = gripper_axes(spread_xy)
    x, y, z = nominal.position
    moved = (x + offset.dx * xx + offset.dy * yx, y + offset.dx * xy + offset.dy * yy, z)
    return PartPose(position=moved, yaw_deg=nominal.yaw_deg + offset.yaw_deg)


def yaw_quaternion(yaw_deg: float) -> tuple[float, float, float, float]:
    """Rotation about +Z as (w, x, y, z), Isaac's scalar-first order."""
    half = math.radians(yaw_deg) / 2
    return (math.cos(half), 0.0, 0.0, math.sin(half))
