"""Finger geometry: a design for a part -> the convex pieces of one printed finger, and how to grasp with it.

Coordinates are the gripper frame G at the grasp, in mm, with the jaws closed (jaw = 0): origin between the stock
fingertips, +z up toward the wrist, +x along the jaw travel toward the finger described here, +y = z cross x. The other
finger is this one mirrored in x. The stock blade occupies x 0..12, y -3..3, z 0..76 (inner face at x = 0). Every design
keeps the fingertips at z = 0, so the 293 mm TCP stays as calibrated, and keeps the blade's top MOUNT_MM, where it's
screwed to the jaw.

A finger is that upper blade, a bridge, and a contact pad. The pad's inner face follows a profile across the jaws (flat,
a V groove, or the imprint's pocket), runs straight down to the fingertips, and can have a 45 degree lead-in chamfer along
its bottom inner edge. Physics engines collide convex shapes fast, so the pad is built as convex strips, one per straight
segment of the profile, the way the twin builds its own fingers. The sim server receives exactly these pieces.
"""

import math
from collections.abc import Callable
from itertools import pairwise

import numpy as np
from pydantic import BaseModel
from scipy.spatial import ConvexHull

from api.models.design import Design
from api.models.part import Part

STROKE_MM = 6.0  # jaw travel, per jaw (SMC MHZL2-16D2): 0 closed, 6 open
BLADE_MM = (12.0, 6.0, 76.0)  # stock blade: width along x, thickness along y, length along z
MOUNT_MM = 30.0  # top of the blade kept as stock, where it's screwed to the jaw
BRIDGE_MM = 4.0  # the step joining an offset pad to the blade
WALL_MM = 3.0  # material behind the deepest point of the pad face
SQUEEZE_MM = 0.3  # per jaw: the jaws are driven this far past the seated position, to grip
SEAT_GAP_MM = 0.5  # gripping, each pad face stays this far from the part's centre plane, so the fingers never touch
TOP_CLEARANCE_MM = 3.0  # the pad reaches this far above the part's top, so the bridge clears it
IMPRINT_CLEARANCE_MM = 0.2
PRINTED_FRICTION = (0.6, 0.5)  # static, dynamic: an estimate for PLA/PETG; measure the real print with a tilt test
ENVELOPE_MM = (45.0, 30.0)  # how far a finger may reach in |x| (jaws open) and |y| before it could hit the gripper or camera

Point = tuple[float, float, float]
Polygon = list[tuple[float, float]]
Profile = list[tuple[float, float]]  # (y, recess) breakpoints across the pad: how far the face is set back at each y


class Piece(BaseModel):
    """A convex solid: the hull of its points. The triangles are its faces, wound counter-clockwise seen from outside."""

    points: list[Point]
    triangles: list[tuple[int, int, int]]


class Finger(BaseModel):
    """One finger's geometry and how to grasp with it: what a design produces and what the sim server tests."""

    pieces: list[Piece]
    tip_height_mm: float  # fingertips above the table when gripping
    jaw_close_mm: float  # per jaw, from closed: where the jaws are driven to grip
    contact_mm: float  # height of pad face that touches the part
    friction: tuple[float, float] = PRINTED_FRICTION

    @property
    def grasp_pose(self) -> dict:
        """The grasp to give the robot with these fingers. The TCP is unchanged, since the fingertips don't move."""
        return {
            "approach": "top-down, centred on the part, jaws closing along its width",
            "tip_height_mm": round(self.tip_height_mm, 2),
            "jaw_open_mm": STROKE_MM,
            "jaw_close_mm": round(self.jaw_close_mm, 2),
            "tcp_mm": 293,
        }


def build_finger(part: Part, design: Design) -> Finger:
    """The finger a design describes, for this part. The stock fingers aren't ours to build (see stock_finger())."""
    if design.kind == "stock":
        raise ValueError("the stock fingers are already on the robot; stock_finger() is the mock's stand-in")
    if design.kind == "imprint":
        return _imprint(part)
    p = design.params
    profile = v_profile(p["pad_width_mm"], p.get("groove_angle_deg", 180.0), p.get("groove_depth_mm", 0.0))
    face = p["slack_mm"] + part.extent_mm[0] / 2 - STROKE_MM  # where the pad face sits with the jaws closed
    jaw_close = seat_distance(part, profile) - face - SQUEEZE_MM
    return _assemble(part, profile, face, p["tip_height_mm"], p["lead_in_mm"], jaw_close)


def stock_finger(part: Part) -> Finger:
    """A stand-in for the stock aluminium fingers, for the mock simulator: flat 6 mm faces meeting at x = 0, and a 2 mm
    lead-in where the hooked tips open to 16 mm. The sim server uses the real fingers."""
    face = [(-BLADE_MM[1] / 2, 0.0), (BLADE_MM[1] / 2, 0.0)]
    return _assemble(part, face, 0.0, tip=1.5, lead=2.0, jaw_close=max(0.0, part.extent_mm[0] / 2 - SQUEEZE_MM))


def v_profile(width: float, angle_deg: float, depth: float) -> Profile:
    """A pad face with a V groove in the middle; flat when the angle is 180 or the depth 0."""
    half = width / 2
    if depth <= 0 or angle_deg >= 180:
        return [(-half, 0.0), (half, 0.0)]
    t = math.tan(math.radians(angle_deg / 2))
    mouth = depth * t
    if mouth >= half:  # the groove spans the whole pad
        return [(-half, depth - half / t), (0.0, depth), (half, depth - half / t)]
    return [(-half, 0.0), (-mouth, 0.0), (0.0, depth), (mouth, 0.0), (half, 0.0)]


def seat_distance(part: Part, profile: Profile) -> float:
    """How far in front of the pad face the part's centre sits once both fingers grip it. A box rests on the deepest
    part of the face; a round part settles where the profile first touches it."""
    x = part.extent_mm[0]
    ys, recess = np.array([y for y, _ in profile]), np.array([e for _, e in profile])
    if not part.round_from_above:
        return x / 2 - float(recess.max())
    r = x / 2
    lo, hi = max(-r, ys[0]), min(r, ys[-1])
    samples = np.concatenate([np.linspace(lo, hi, 401), ys[(ys >= lo) & (ys <= hi)]])
    return float(np.max(np.sqrt(np.maximum(r * r - samples * samples, 0.0)) - np.interp(samples, ys, recess)))


def problems(part: Part, finger: Finger) -> list[str]:
    """What rules a finger out before any physics. Designs from the search space pass by construction; this guards the
    rest and is checked before anything is simulated or exported."""
    _, _, height = part.extent_mm
    out = []
    if finger.tip_height_mm < 0.5:
        out.append("the fingertips would scrape the table")
    if not 0 <= finger.jaw_close_mm <= STROKE_MM:
        out.append(f"the jaws can't reach the gripping position ({finger.jaw_close_mm:.2f} mm; travel is 0..{STROKE_MM:g})")
    if finger.contact_mm < 1:
        out.append("less than 1 mm of pad touches the part")
    if height - finger.tip_height_mm + TOP_CLEARANCE_MM + BRIDGE_MM > BLADE_MM[2] - MOUNT_MM:
        out.append("the part is too tall: the pad would have to reach into the mount")
    points = [pt for piece in finger.pieces for pt in piece.points]
    if min(x for x, _, _ in points) + finger.jaw_close_mm <= 0:
        out.append("the fingers would touch each other before gripping the part")
    if max(abs(x) for x, _, _ in points) + STROKE_MM > ENVELOPE_MM[0] or max(abs(y) for _, y, _ in points) > ENVELOPE_MM[1]:
        out.append("the finger reaches outside the space the gripper and its camera leave free")
    centred = {"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}
    part_top = height - finger.tip_height_mm
    if part_top > 0 and any(overlaps(p, part, centred) for z in (1e-6, part_top / 2, part_top) for p in sections(finger, z, STROKE_MM)):
        out.append("with the jaws open, a finger would land on the centred part")
    return out


def sections(finger: Finger, z: float, jaw: float) -> list[Polygon]:
    """Both fingers' cross-sections at height z (fingertips at 0) with the jaws at this position: this finger moved out
    along +x, its mirror image along -x."""
    out = []
    for piece in finger.pieces:
        if polygon := section(piece, z):
            out.append([(x + jaw, y) for x, y in polygon])
            out.append([(-(x + jaw), y) for x, y in reversed(polygon)])
    return out


def section(piece: Piece, z: float) -> Polygon:
    """The piece's cross-section at height z: a convex polygon, counter-clockwise, empty if the plane misses it."""
    pts, cut = piece.points, []
    for tri in piece.triangles:
        for i, j in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            (ax, ay, az), (bx, by, bz) = pts[i], pts[j]
            if az == z:
                cut.append((ax, ay))
            elif (az - z) * (bz - z) < 0:
                t = (z - az) / (bz - az)
                cut.append((ax + t * (bx - ax), ay + t * (by - ay)))
    return _hull2d(cut)


def overlaps(polygon: Polygon, part: Part, offset: dict, margin: float = 0.0) -> bool:
    """Whether a convex polygon in G's x-y plane overlaps the part's outline seen from above, at this camera error."""
    cx, cy = offset["dx"], offset["dy"]
    x, y, _ = part.extent_mm
    if part.round_from_above:
        return _overlaps_circle(polygon, (cx, cy), x / 2 + margin)
    a = math.radians(offset.get("yaw_deg", 0.0))
    c, s, hx, hy = math.cos(a), math.sin(a), x / 2 + margin, y / 2 + margin
    outline = [(cx + c * u - s * v, cy + s * u + c * v) for u, v in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
    return _overlaps_polygon(polygon, outline)


def _imprint(part: Part) -> Finger:
    """A pocket shaped like the part, gripping it with the jaws almost closed so it wraps as far as the fingers can
    without touching each other: low fingertips, no lead-in, no slack, as a designer copying the part's shape would draw
    it. A box (or a lying cylinder: a curved cradle isn't modelled) gets a rectangular notch, or a plain flat face where
    a notch as long as the part wouldn't fit beside the gripper."""
    x, y, _ = part.extent_mm
    jaw_seat = 2 * SQUEEZE_MM
    notch = y / 2 + IMPRINT_CLEARANCE_MM
    if part.round_from_above:
        profile = _pocket_profile(x / 2 + IMPRINT_CLEARANCE_MM, SEAT_GAP_MM, shoulder=WALL_MM)
    elif notch + WALL_MM + 0.3 <= ENVELOPE_MM[1]:
        profile = _notch_profile(notch, x / 2 - SEAT_GAP_MM, shoulder=WALL_MM)
    else:
        profile = [(1 - ENVELOPE_MM[1], 0.0), (ENVELOPE_MM[1] - 1, 0.0)]
        return _assemble(part, profile, x / 2 - jaw_seat, tip=1.0, lead=0.0, jaw_close=jaw_seat - SQUEEZE_MM)
    return _assemble(part, profile, SEAT_GAP_MM - jaw_seat, tip=1.0, lead=0.0, jaw_close=jaw_seat - SQUEEZE_MM)


def _pocket_profile(radius: float, centre: float, shoulder: float, segments: int = 16) -> Profile:
    """A circular pocket: the circle of this radius around a point `centre` mm in front of the face, cut into the pad."""
    mouth = math.sqrt(radius**2 - centre**2)
    arc = [(y, max(0.0, math.sqrt(max(radius**2 - y**2, 0.0)) - centre)) for y in np.linspace(-mouth, mouth, segments + 1)]
    return [(-mouth - shoulder, 0.0), *arc, (mouth + shoulder, 0.0)]


def _notch_profile(half_width: float, depth: float, shoulder: float, draft: float = 0.3) -> Profile:
    """A rectangular pocket with slightly drafted sides."""
    w = half_width
    return [(-w - draft - shoulder, 0.0), (-w - draft, 0.0), (-w, depth), (w, depth), (w + draft, 0.0), (w + draft + shoulder, 0.0)]


def _assemble(part: Part, profile: Profile, face: float, tip: float, lead: float, jaw_close: float) -> Finger:
    """Pad strips under a bridge under the stock upper blade. The pad reaches from the fingertips to above the part, and
    is thick enough to keep a full wall behind both the deepest groove and the lead-in chamfer."""
    height = part.extent_mm[2]
    back = face + max(e for _, e in profile) + lead + WALL_MM
    pad_top = height - tip + TOP_CLEARANCE_MM
    pieces = [_strip(face, back, a, b, pad_top, lead) for a, b in pairwise(profile)]
    half = max(BLADE_MM[1] / 2, -profile[0][0], profile[-1][0])
    blade_bottom = pad_top + BRIDGE_MM
    pieces.append(_box((min(0.0, face), max(BLADE_MM[0], back)), (-half, half), (pad_top, blade_bottom)))
    if blade_bottom < BLADE_MM[2]:
        pieces.append(_box((0.0, BLADE_MM[0]), (-BLADE_MM[1] / 2, BLADE_MM[1] / 2), (blade_bottom, BLADE_MM[2])))
    return Finger(pieces=pieces, tip_height_mm=tip, jaw_close_mm=jaw_close, contact_mm=max(0.0, height - tip - lead))


def _strip(face: float, back: float, a: tuple[float, float], b: tuple[float, float], top: float, lead: float) -> Piece:
    """The pad between two profile breakpoints, from the fingertips up to `top`, cut along its bottom inner edge by the
    lead-in plane x + z = face + lead."""
    (y0, e0), (y1, e1) = a, b
    quad = [(face + e0, y0), (face + e1, y1), (back, y1), (back, y0)]
    points = [(x, y, z) for z in (0.0, top) for x, y in quad]
    if lead > 0:
        edges = [(i, (i + 1) % 4) for i in range(4)] + [(4 + i, 4 + (i + 1) % 4) for i in range(4)] + [(i, i + 4) for i in range(4)]
        points = _clip(points, edges, lambda p: p[0] + p[2] - (face + lead))
    return _hull(points)


def _box(xs: tuple[float, float], ys: tuple[float, float], zs: tuple[float, float]) -> Piece:
    return _hull([(x, y, z) for x in xs for y in ys for z in zs])


def _clip(points: list[Point], edges: list[tuple[int, int]], side: Callable[[Point], float]) -> list[Point]:
    """A convex polyhedron (its corners and edges) cut by a plane: the corners on the kept side (side >= 0) plus the
    points where edges cross the plane."""
    kept = [p for p in points if side(p) >= 0]
    for i, j in edges:
        si, sj = side(points[i]), side(points[j])
        if si * sj < 0:
            t = si / (si - sj)
            kept.append(tuple(a + t * (b - a) for a, b in zip(points[i], points[j], strict=True)))
    return kept


def _hull(points: list[Point]) -> Piece:
    pts = np.unique(np.round(np.asarray(points, float), 6), axis=0)
    hull = ConvexHull(pts)
    triangles = []
    for (a, b, c), plane in zip(hull.simplices, hull.equations, strict=True):
        if np.dot(np.cross(pts[b] - pts[a], pts[c] - pts[a]), plane[:3]) < 0:
            b, c = c, b
        triangles.append((int(a), int(b), int(c)))
    used = sorted({i for t in triangles for i in t})
    index = {old: new for new, old in enumerate(used)}
    return Piece(points=[tuple(float(v) for v in pts[i]) for i in used], triangles=[tuple(index[i] for i in t) for t in triangles])


def _hull2d(points: Polygon) -> Polygon:
    """Convex hull, counter-clockwise (Andrew's monotone chain). Fewer than 3 distinct points: no area, so empty."""
    pts = sorted({(round(x, 9), round(y, 9)) for x, y in points})
    if len(pts) < 3:
        return []

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and _cross(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]

    hull = half(pts) + half(reversed(pts))
    return hull if len(hull) >= 3 else []


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _overlaps_circle(polygon: Polygon, centre: tuple[float, float], radius: float, eps: float = 1e-9) -> bool:
    if not polygon:
        return False
    if all(_cross(a, b, centre) >= 0 for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True)):
        return True  # the centre is inside the polygon
    return any(_segment_distance(centre, a, b) < radius - eps for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True))


def _segment_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy or 1.0)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _overlaps_polygon(a: Polygon, b: Polygon, eps: float = 1e-9) -> bool:
    """Separating-axis test for two convex polygons; touching doesn't count."""
    for poly in (a, b):
        for p, q in zip(poly, poly[1:] + poly[:1], strict=True):
            nx, ny = q[1] - p[1], p[0] - q[0]
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if max(pa) <= min(pb) + eps or max(pb) <= min(pa) + eps:
                return False
    return True
