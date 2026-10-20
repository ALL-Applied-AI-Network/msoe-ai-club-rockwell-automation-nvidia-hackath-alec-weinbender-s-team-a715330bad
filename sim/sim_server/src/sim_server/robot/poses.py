"""Where the part is placed for each grasp, and where it ends up in the hand.

Isaac-free and numpy-free (the HTTP layer imports the service that imports this). Poses are in the robot base frame, the
twin's planning frame: origin on the base mounting face, +X away from the robot, +Y to its left, +Z up; the work surface
is at z = SURFACE_DZ. World = base + (0, 0, TABLE_TOP_Z) + the environment's origin, a pure translation, so the in-hand
pose comes out the same whichever of the two frames its inputs are in.

The nominal grasp site is (0.30, 0.0), straight below the twin's home pose (fingertips at (0.30, 0, 0.24)), so the
approach is a vertical move and the arm is well inside its reach (the twin's cube picks span x 0.24..0.46). The jaws
close along base Y there, as for the twin's tower placements. The part's own frame has x along the closing direction
(toward JawL), y across it and z up, with its origin at mid-height above the grasp centre, so a box's box_mm, a lying
cylinder's axis and a mesh's pieces line up with the jaws at the nominal pose.

The true pose (camera-error model) shifts and turns the part in the gripper's frame at the grasp. Only the world is set
up from it; the robot always plans at the nominal pose (the twin's rule: ground truth never feeds grasp commands).
"""

import math
from collections.abc import Sequence

from sim_server.models.offset import Offset
from sim_server.models.part import CylinderAxis, Part
from sim_server.models.pose import InHandPose, PartPose

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


def in_hand_pose(
    part_position: Sequence[float],
    part_orientation: Sequence[float],
    grip_origin: Sequence[float],
    spread_xy: tuple[float, float],
    expected_z: float,
    cylinder_axis: CylinderAxis | None = None,
) -> InHandPose:
    """The part's pose relative to the commanded gripper frame G, minus where a perfectly centred part would sit.

    G is the frame the robot was told to be at, not where the arm measurably is: a placement after the pick uses the
    commanded pose too, so this is the error the placement inherits. Its origin is grip_origin (the commanded fingertip
    point), x the spread direction toward JawL, z up and y = z x x. A centred part sits at (0, 0, expected_z) in G
    (half its height minus the tip height, at the end of the lift).

    part_orientation is a quaternion (w, x, y, z); any non-zero length. For a box or a mesh, tilt is the angle between
    the part's z axis and G's z, and yaw is the angle of the part's x axis, projected onto G's xy plane, from G's x
    about G's z, in (-180, 180].

    A cylinder looks the same however far it has turned about its own axis (cylinder_axis), so its angles follow that
    axis alone and a roll in the jaws reads zero. Standing ("z"): tilt is the axis's angle from G's z, and yaw is 0.
    Lying ("y" across the jaws, "x" along them): tilt is the axis's angle out of G's xy plane, and yaw is the turn of
    its projection about G's z from where it started (G's y or x), in (-90, 90], since its two ends are alike.
    Raises ValueError for a zero or non-finite quaternion."""
    (gxx, gxy), (gyx, gyy) = gripper_axes(spread_xy)
    rx, ry, rz = (p - o for p, o in zip(part_position, grip_origin, strict=True))
    axes = _axes(part_orientation)

    def heading(axis: tuple[float, float, float]) -> float:
        """The angle of an axis's projection onto G's xy plane, from G's x about G's z."""
        return math.degrees(math.atan2(axis[0] * gyx + axis[1] * gyy, axis[0] * gxx + axis[1] * gxy))

    if cylinder_axis in ("x", "y"):
        axis = axes["xyz".index(cylinder_axis)]
        tilt = math.degrees(math.atan2(abs(axis[2]), math.hypot(axis[0], axis[1])))
        turn = heading(axis) - (90.0 if cylinder_axis == "y" else 0.0)
        yaw = (turn + 90.0) % 180.0 - 90.0
        yaw = 90.0 if yaw <= -90.0 else yaw
    else:
        z_axis = axes[2]
        tilt = math.degrees(math.atan2(math.hypot(z_axis[0], z_axis[1]), z_axis[2]))
        yaw = 0.0 if cylinder_axis == "z" else heading(axes[0])
        yaw = yaw + 360.0 if yaw <= -180.0 else yaw
    return InHandPose(dx=rx * gxx + ry * gxy, dy=rx * gyx + ry * gyy, dz=rz - expected_z, tilt_deg=tilt, yaw_deg=yaw)


def _axes(quaternion: Sequence[float]) -> tuple[tuple[float, float, float], ...]:
    """The columns of the rotation matrix of a (w, x, y, z) quaternion, normalised first: the body's x, y and z axes."""
    norm = math.sqrt(sum(v * v for v in quaternion))
    if not norm > 0 or not math.isfinite(norm):
        raise ValueError(f"not a rotation quaternion: {tuple(quaternion)}")
    w, x, y, z = (v / norm for v in quaternion)
    x_axis = (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y))
    y_axis = (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x))
    z_axis = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    return x_axis, y_axis, z_axis
