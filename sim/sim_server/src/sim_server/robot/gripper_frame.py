"""The gripper frame G that custom fingers are drawn in, and how it maps onto the twin's flange and jaw bodies. Isaac-free.

G is fixed to the flange (J6_link). Its origin is the point between the two stock fingertips with the jaws closed: on the
tool axis, in the plane of the fingertips. +z points from the fingertips back toward the wrist (up in a top-down grasp),
+x along FINGER_SPREAD_AXIS toward JawL (the +spread jaw), +y = z x x. In the twin's flange frame (TOOL_AXIS = +X,
FINGER_SPREAD_AXIS = +Y) that is

    x_G = Y_flange,  y_G = -Z_flange,  z_G = tip_offset - X_flange        (tip_offset = 0.293 m, the TCP)

A design's pieces describe the finger on JawL at jaw = 0 (closed); JawR carries the mirror image (x -> -x). At a per-jaw
opening j, JawL's finger is shifted by +j in x and JawR's by -j.

Checked against cell.py (attach_gripper, finger_profile, prism, the jaw joints) by tests/robot/test_gripper_frame.py. At
jaw = 0 the stock blade's bounding box in G is x 0..12 mm, y -3..3 mm, z 0..76 mm: inner face x = 0, 12 mm wide
(FINGER_WIDTH), 6 mm thick (FINGER_THICK) centred on y = 0, fingertip at z = 0 and root at z = 76 mm (FINGER_LENGTH). It
isn't a full box: the AA scallop (radius 7.25 mm, centred at x = 0, z = 6.97 mm) is cut out of the inner face below
z = 14.22 mm, so the hooked tip face at z = 0 spans only x 2.0..7.5 mm, and the outer bevel runs from (x 7.5, z 0) to
(x 12, z 14).
"""

from collections.abc import Sequence

from sim_server.models.finger import Point
from sim_server.models.gripper import GripperGeometry


def geometry_from_twin() -> GripperGeometry:
    """Reads the twin's scene_config (twin.use_twin() must have run). Repeats cell.gripper_layout()'s sum, because cell.py
    needs Isaac; clients/isaac.py checks the two agree at startup."""
    import scene_config as C

    if tuple(C.TOOL_AXIS) != (1.0, 0.0, 0.0) or tuple(C.FINGER_SPREAD_AXIS) != (0.0, 1.0, 0.0):
        raise ValueError(f"G assumes TOOL_AXIS +X and FINGER_SPREAD_AXIS +Y; the twin has {C.TOOL_AXIS}, {C.FINGER_SPREAD_AXIS}")
    carriage_x = C.FLANGE_OFFSET + C.ADAPTER_T + C.ZCYL_LEN + C.ZFLANGE_T + C.BODY_LEN + C.PLATE_T
    return GripperGeometry(
        carriage_x=carriage_x,
        finger_x=carriage_x + C.CARRIAGE_LEN - C.CARRIAGE_OVERLAP,
        finger_length=C.FINGER_LENGTH,
        finger_width=C.FINGER_WIDTH,
        finger_thick=C.FINGER_THICK,
        jaw_open=C.JAW_OPEN,
        jaw_closed=C.JAW_CLOSED,
        finger_inner_tip=C.FINGER_INNER_TIP,
        tip_clearance=C.CUBE_TIP_CLEARANCE,
        surface_dz=C.SURFACE_DZ,
        table_top_z=C.TABLE_TOP_Z,
    )


def flange_from_g(p: Point, geo: GripperGeometry) -> Point:
    x, y, z = p
    return (geo.tip_offset - z, x, -y)


def g_from_flange(p: Point, geo: GripperGeometry) -> Point:
    x, y, z = p
    return (y, -z, geo.tip_offset - x)


def mirror(p: Point) -> Point:
    """JawL's finger to JawR's, in G."""
    return (-p[0], p[1], p[2])


def finger_points_g(points: Sequence[Point], side: int, jaw: float) -> list[Point]:
    """Where the finger on `side` (+1 JawL, -1 JawR) is in G at per-jaw opening `jaw`, given JawL's finger at jaw = 0."""
    return [(side * (x + jaw), y, z) for x, y, z in points]


def jaw_body_origin_flange(side: int, jaw: float, geo: GripperGeometry) -> Point:
    """The jaw body's origin in the flange frame. cell.attach_gripper puts it at at(carriage_x, sign * (jaw + W/2)), and
    the prismatic joint (q = -(JAW_OPEN - jaw) for JawL, +(...) for JawR, see cell.jaw_targets) keeps it there. The jaw
    body's axes stay parallel to the flange's: the joint has no local rotations."""
    return (geo.carriage_x, side * (jaw + geo.finger_width / 2), 0.0)


def jaw_body_points(points: Sequence[Point], side: int, geo: GripperGeometry) -> list[Point]:
    """JawL's finger points (G, jaws closed) in the frame of the jaw body on `side`, where the colliders are authored.
    Independent of the opening, since the finger rides on the jaw body. JawR gets the mirror image."""
    a = geo.tip_offset - geo.carriage_x
    return [(a - z, side * (x - geo.finger_width / 2), -y) for x, y, z in points]


def jaw_body_triangles(triangles: Sequence[tuple[int, int, int]], side: int) -> list[tuple[int, int, int]]:
    """Mirroring flips handedness, so JawR's copy reverses the winding to keep faces pointing outward."""
    return [tuple(t) for t in triangles] if side > 0 else [(c, b, a) for a, b, c in triangles]


def stock_profile_g(profile: Sequence[tuple[float, float]], geo: GripperGeometry) -> list[tuple[float, float]]:
    """gripper_geometry.finger_profile() as (x, z) in G. Its (u, v) runs u root -> tip along the blade and v outward
    from the inner face; cell.py extrudes it FINGER_THICK along the jaw's Z, centred, so y spans +-FINGER_THICK / 2."""
    return [(v, geo.finger_length - u) for u, v in profile]
