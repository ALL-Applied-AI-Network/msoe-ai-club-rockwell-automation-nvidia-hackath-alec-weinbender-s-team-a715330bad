"""Finger geometry: a design for a part -> the finger's CAD solid, its convex pieces, and how to grasp with it.

The gripper (stroke, stock blade, kept mount, free space, pad friction) comes from the cell profile
(api/models/cell_profile.py: Gripper); None means Gripper(), the UWM CSI cell's, which the module constants below repeat
for callers that only need the defaults.

Coordinates are the gripper frame G at the grasp, in mm, with the jaws closed (jaw = 0): origin between the stock
fingertips, +z up toward the wrist, +x along the jaw travel toward the finger described here, +y = z cross x. The other
finger is this one mirrored in x. The stock blade occupies x 0..12, y -3..3, z 0..76 (inner face at x = 0). Every design
keeps the fingertips at z = 0, so the 293 mm TCP stays as calibrated, and keeps the blade's top (Gripper.mount_kept_mm),
where it's screwed to the jaw.

A finger is that upper blade, a bridge, and a contact pad. The pad's inner face follows a profile across the jaws (flat,
a V groove, or the imprint's pocket), runs straight down to the fingertips, and can have a 45 degree lead-in chamfer along
its bottom inner edge.

A design's parameters are relative to the part it's built for (the pad face sits slack_mm off it, the pad reaches 3 mm
above its top), so a finger is built once, for the job's primary resting pose. In any other pose the same physical
finger only grips differently: regrip() works out where the jaws close and how high the fingertips go there.

CadQuery builds it, so the CAD is the ground truth. Physics engines collide convex shapes fast and reliably, so the finger
is built as convex solids (one per straight segment of the profile, plus the bridge and the blade, the way the twin
builds its own fingers): the sim server receives exactly those solids, tessellated, as `pieces`, and finger_cad.py fuses
the same solids (finger_solids()) and adds the mount features for the printable STEP/STL. Those don't change the
collision shape.

Seen from above, the part is a circle (round from above: a cylinder standing on an end), a rectangle (a box, or a lying
cylinder: one lying along the jaws, axis "x", is gripped by its end faces and looks like a box from above), or, for a
mesh, the union of its convex pieces' footprints. A mesh is seated by the box rule (its bounding box), which is exact for
parts whose gripped sides are flat and parallel and an approximation otherwise. A section grip (Part.grip_width_mm and
grip_span_mm: a screw's shank beside its head) is seated by the box rule on the section, and the pads must stay within
its span.
"""

import math
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise

import cadquery as cq
import numpy as np
from pydantic import BaseModel

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.part import Part
from api.models.piece import Piece, Point, hull_piece  # noqa: F401 (re-exported: callers import Piece from here)

DEFAULT_GRIPPER = Gripper()
STROKE_MM = DEFAULT_GRIPPER.stroke_mm  # jaw travel, per jaw (SMC MHZL2-16D2): 0 closed, 6 open
BLADE_MM = DEFAULT_GRIPPER.blade_mm  # stock blade: width along x, thickness along y, length along z
MOUNT_MM = DEFAULT_GRIPPER.mount_kept_mm  # top of the blade kept as stock, where it's screwed to the jaw
ENVELOPE_MM = DEFAULT_GRIPPER.free_space_mm  # how far a finger may reach in |x| (jaws open) and |y|
PRINTED_FRICTION = DEFAULT_GRIPPER.pad_friction  # static, dynamic: an estimate for PLA/PETG; measure with a tilt test
BRIDGE_MM = 4.0  # the step joining an offset pad to the blade
WALL_MM = 3.0  # material behind the deepest point of the pad face
SQUEEZE_MM = 0.3  # per jaw: the jaws are driven this far past the seated position, to grip
SEAT_GAP_MM = 0.5  # gripping, each pad face stays this far from the part's centre plane, so the fingers never touch
TOP_CLEARANCE_MM = 3.0  # the pad reaches this far above the part's top, so the bridge clears it
IMPRINT_CLEARANCE_MM = 0.2
STOCK_TIP_MM = 2.5  # the stock fingertips' height above the table when gripping: the twin's cube rule, as the sim runs it
MIN_TIP_MM = 1.0  # fingertips above the table
MIN_CONTACT_MM = 2.0  # pad face left on the part, between the grip height and the top of the lead-in
BRIDGE_CLEARANCE_MM = 0.5  # in another pose, the part's top stays at least this far below the bridge

Polygon = list[tuple[float, float]]
Profile = list[tuple[float, float]]  # (y, recess) breakpoints across the pad: how far the face is set back at each y


class Finger(BaseModel):
    """One finger's geometry and how to grasp with it: what a design produces and what the sim server tests."""

    pieces: list[Piece]
    tip_height_mm: float  # fingertips above the table when gripping
    jaw_close_mm: float  # per jaw, from closed: where the jaws are driven to grip
    contact_mm: float  # height of pad face that touches the part
    friction: tuple[float, float] = PRINTED_FRICTION
    # Reported, never searched (D2): the gap between the two pad faces with the jaws fully closed, 2 x the face's x. The
    # smallest part these fingers can still grip; negative where the faces would pass each other (the imprint's shoulders).
    # None for a Finger built elsewhere.
    closed_gap_mm: float | None = None
    jaw_open_mm: float = STROKE_MM  # per jaw: the gripper's stroke, where the jaws are before closing
    tcp_mm: float = DEFAULT_GRIPPER.tcp_mm
    # The pad's top above the fingertips, where the bridge starts: fixed by the part it was built for. None for a Finger
    # built elsewhere.
    pad_top_mm: float | None = None

    @property
    def grasp_pose(self) -> dict:
        """The grasp to give the robot with these fingers. The TCP is unchanged, since the fingertips don't move."""
        return {
            "approach": "top-down, centred on the part, jaws closing along its width",
            "tip_height_mm": round(self.tip_height_mm, 2),
            "jaw_open_mm": self.jaw_open_mm,
            "jaw_close_mm": round(self.jaw_close_mm, 2),
            "tcp_mm": self.tcp_mm,
        }


@dataclass(frozen=True)
class _Layout:
    """Where a finger's pad goes: its face profile, the face's x with the jaws closed, and the grasp it implies."""

    profile: Profile
    face: float
    tip: float
    lead: float
    jaw_close: float


def build_finger(part: Part, design: Design, gripper: Gripper | None = None) -> Finger:
    """The finger a design describes, for this part: its convex solids, tessellated. The stock fingers aren't ours to
    build (see stock_finger())."""
    g = gripper or DEFAULT_GRIPPER
    return _finger(part, _layout(part, design, g), g)


def regrip(
    built_for: Part,
    part: Part,
    design: Design,
    gripper: Gripper | None = None,
    *,
    tip_height_mm: float | None = None,
    built: Finger | None = None,
) -> Finger:
    """The finger built for `built_for` (its pieces unchanged) gripping `part`, the same part in another resting pose:
    the jaws close to where this pose seats against the pad face, and the fingertips go to the pose's own grip height
    (tip_height_mm, when its grasp locks one), else to the design's, raised just enough that a taller pose keeps the
    clearance under the bridge it was built with, and lowered to leave MIN_CONTACT_MM of pad (above any lead-in) on a
    shorter one, down to MIN_TIP_MM: lower than that, the pose is too short for this finger. The
    stock fingers are the robot's own: stock_finger(part). `built`: the finger already built for `built_for`, so its
    pieces aren't built again. For the pose it was built for, without a lock, this is build_finger()."""
    g = gripper or DEFAULT_GRIPPER
    if design.kind == "stock":
        return stock_finger(part, g)
    layout = _layout(built_for, design, g)
    finger = built if built is not None else _finger(built_for, layout, g)
    if tip_height_mm is None and (part is built_for or part == built_for):
        return finger
    height, built_height = part.extent_mm[2], built_for.extent_mm[2]
    if tip_height_mm is None:
        lo = max(MIN_TIP_MM, height - (built_height - layout.tip))
        tip = max(MIN_TIP_MM, min(max(layout.tip, lo), height - MIN_CONTACT_MM - layout.lead))  # pad above the lead-in
    else:
        tip = tip_height_mm
    return finger.model_copy(
        update={
            "tip_height_mm": tip,
            "jaw_close_mm": seat_distance(part, layout.profile) - layout.face - SQUEEZE_MM,
            "contact_mm": max(0.0, height - tip - layout.lead),
        }
    )


def finger_solids(part: Part, design: Design, gripper: Gripper | None = None) -> list[cq.Solid]:
    """The finger's convex solids, exactly as simulated (one per pad strip, the bridge, the kept blade). The printable
    solid (api/models/finger_cad.py) fuses these and adds the mount features."""
    g = gripper or DEFAULT_GRIPPER
    return _solids(part, _layout(part, design, g), g)


def stock_finger(part: Part, gripper: Gripper | None = None) -> Finger:
    """A stand-in for the stock aluminium fingers, for the mock simulator: flat faces as thick as the blade, meeting at
    x = 0, and a lead-in where the hooked tips open wider than the faces (16 mm against 12 mm on the UWM cell: 2 mm per
    side). The sim server uses the real fingers."""
    g = gripper or DEFAULT_GRIPPER
    face = [(-g.blade_mm[1] / 2, 0.0), (g.blade_mm[1] / 2, 0.0)]
    lead = max(0.0, g.stock_tip_gap_mm / 2 - g.stroke_mm)
    jaw_close = max(0.0, part.grip_width / 2 - SQUEEZE_MM)
    return _finger(part, _Layout(face, 0.0, tip=STOCK_TIP_MM, lead=lead, jaw_close=jaw_close), g)


def stock_grasp_pose(part: Part, gripper: Gripper | None = None) -> dict:
    """The grasp the robot runs with its stock fingers, as the sim server's stock baseline does (the twin's cube rule):
    tips STOCK_TIP_MM up, each jaw closed to SQUEEZE_MM past where its hooked tip meets the part. The hooked tips sit
    (stock tip gap / 2 - stroke) outside the straight face, so this jaw position is that much less than the stand-in
    finger's, whose flat face stands where the tips grip."""
    g = gripper or DEFAULT_GRIPPER
    inner_tip = max(0.0, g.stock_tip_gap_mm / 2 - g.stroke_mm)
    jaw = min(g.stroke_mm, max(0.0, part.grip_width / 2 - inner_tip - SQUEEZE_MM))
    return {
        "approach": "top-down, centred on the part, jaws closing along its width (the stock fingers' own grasp)",
        "tip_height_mm": STOCK_TIP_MM,
        "jaw_open_mm": g.stroke_mm,
        "jaw_close_mm": round(jaw, 2),
        "tcp_mm": g.tcp_mm,
    }


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
    """How far in front of the pad face the part's centre sits once both fingers grip it. A part that isn't round from
    above (a box, a lying cylinder, a mesh by its bounding box) has a flat side: it rests on the most forward point of
    the face across its own width (the whole notch of an imprint shaped to it; a groove's shoulders, for one built for
    another pose; a section grip is seated across its span); a round part settles where the profile first touches it."""
    x = part.grip_width
    ys, recess = np.array([y for y, _ in profile]), np.array([e for _, e in profile])
    if not part.round_from_above:
        span = part.grip_span
        lo, hi = max(span[0], ys[0]), min(span[1], ys[-1])
        window = np.concatenate([[lo, hi], ys[(ys >= lo) & (ys <= hi)]])
        return x / 2 - float(np.interp(window, ys, recess).min())
    r = x / 2
    lo, hi = max(-r, ys[0]), min(r, ys[-1])
    samples = np.concatenate([np.linspace(lo, hi, 401), ys[(ys >= lo) & (ys <= hi)]])
    return float(np.max(np.sqrt(np.maximum(r * r - samples * samples, 0.0)) - np.interp(samples, ys, recess)))


def problems(part: Part, finger: Finger, gripper: Gripper | None = None, *, clearance_mm: float | None = None) -> list[str]:
    """What rules a finger out before any physics. Designs from the search space pass by construction; this guards the
    rest and is checked before anything is simulated or exported. clearance_mm, when given, is the free space around the
    part on the table (its neighbours): with the jaws open the pads must stay within it."""
    g = gripper or DEFAULT_GRIPPER
    x, y, height = part.extent_mm
    blade_length = g.blade_mm[2]
    out = []
    if finger.tip_height_mm < 0.5:
        out.append("the fingertips would scrape the table")
    if not 0 <= finger.jaw_close_mm <= g.stroke_mm:
        out.append(f"the jaws can't reach the gripping position ({finger.jaw_close_mm:.2f} mm; travel is 0..{g.stroke_mm:g})")
    if finger.contact_mm < 1:
        out.append("less than 1 mm of pad touches the part")
    # The pad's top is where the finger was built to reach: above this part's top (plus the clearance), unless it was
    # built for another pose, and then the part may reach the bridge.
    pad_top = finger.pad_top_mm if finger.pad_top_mm is not None else height - finger.tip_height_mm + TOP_CLEARANCE_MM
    if pad_top + BRIDGE_MM > blade_length - g.mount_kept_mm:
        out.append("the part is too tall: the pad would have to reach into the mount")
    if height - finger.tip_height_mm > pad_top - BRIDGE_CLEARANCE_MM:
        out.append("the part's top would reach the bridge above the pad")
    points = [pt for piece in finger.pieces for pt in piece.points]
    if min(px for px, _, _ in points) + finger.jaw_close_mm <= 0:
        out.append("the fingers would touch each other before gripping the part")
    free_x, free_y = g.free_space_mm
    if max(abs(px) for px, _, _ in points) + g.stroke_mm > free_x or max(abs(py) for _, py, _ in points) > free_y:
        out.append("the finger reaches outside the space the gripper and its camera leave free")
    centred = {"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}
    part_top = height - finger.tip_height_mm
    heights = (1e-6, part_top / 2, part_top)
    if part_top > 0 and any(overlaps(p, part, centred) for z in heights for p in sections(finger, z, g.stroke_mm)):
        out.append("with the jaws open, a finger would land on the centred part")
    if part.grip_span_mm is not None and part_top > 0:
        pads = [py for z in (1e-6, part_top) for piece in finger.pieces for _, py in section(piece, z)]
        lo, hi = part.grip_span_mm
        if pads and (min(pads) < lo - 1e-6 or max(pads) > hi + 1e-6):
            out.append("the pads would reach the wider part beside the grip")
    if clearance_mm is not None and part_top > 0:
        pads = [polygon for z in (1e-6, part_top) for piece in finger.pieces if (polygon := section(piece, z))]
        if pads:
            beside_x = max(px for polygon in pads for px, _ in polygon) + g.stroke_mm - x / 2
            beside_y = max(abs(py) for polygon in pads for _, py in polygon) - y / 2
            need = max(beside_x, beside_y)
            if need > clearance_mm + 1e-6:
                out.append(f"the finger needs {need:.1f} mm beside the part, and the part has {clearance_mm:g} mm of clearance")
    return out


def sections(finger: Finger, z: float, jaw: float) -> list[Polygon]:
    """Both fingers' cross-sections at height z (fingertips at 0) with the jaws at this position: this finger moved out
    along +x, its mirror image along -x."""
    out = []
    for piece in finger.pieces:
        if polygon := section(piece, z):
            out.append([(px + jaw, py) for px, py in polygon])
            out.append([(-(px + jaw), py) for px, py in reversed(polygon)])
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
    """Whether a convex polygon in G's x-y plane overlaps the part's outline seen from above, at this camera error: the
    part turned by yaw_deg about the grasp centre, then shifted by (dx, dy). A mesh's outline is its pieces' footprints
    (each piece's convex hull seen from above), so a hollow or L-shaped part leaves room where it has none."""
    cx, cy = offset["dx"], offset["dy"]
    if part.round_from_above:
        return _overlaps_circle(polygon, (cx, cy), part.diameter_mm / 2 + margin)
    a = math.radians(offset.get("yaw_deg", 0.0))
    c, s = math.cos(a), math.sin(a)
    if part.shape == "mesh":
        # Move the polygon into the part's own frame rather than every footprint into G's: same answer, less work.
        local = [((px - cx) * c + (py - cy) * s, -(px - cx) * s + (py - cy) * c) for px, py in polygon]
        lx, ly = [px for px, _ in local], [py for _, py in local]
        box = (min(lx) - margin, min(ly) - margin, max(lx) + margin, max(ly) + margin)
        return any(_boxes_meet(box, bounds) and _overlaps_polygon(local, footprint, margin) for footprint, bounds in footprints(part))
    x, y, _ = part.extent_mm
    hx, hy = x / 2 + margin, y / 2 + margin
    outline = [(cx + c * u - s * v, cy + s * u + c * v) for u, v in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]
    return _overlaps_polygon(polygon, outline)


def footprints(part: Part) -> list[tuple[Polygon, tuple[float, float, float, float]]]:
    """A mesh part's pieces seen from above: each piece's points projected to x-y and their convex hull, with its
    bounding box (min x, min y, max x, max y). Cached, since the mock checks every offset against them."""
    if part.shape != "mesh":
        raise ValueError(f"a {part.shape} has no pieces")
    return _footprints(tuple(tuple(piece.points) for piece in part.pieces))


@lru_cache(maxsize=16)
def _footprints(pieces: tuple[tuple[Point, ...], ...]) -> list[tuple[Polygon, tuple[float, float, float, float]]]:
    out = []
    for points in pieces:
        hull = _hull2d([(px, py) for px, py, _ in points])
        if hull:
            xs, ys = [px for px, _ in hull], [py for _, py in hull]
            out.append((hull, (min(xs), min(ys), max(xs), max(ys))))
    return out


def _layout(part: Part, design: Design, g: Gripper) -> _Layout:
    if design.kind == "stock":
        raise ValueError("the stock fingers are already on the robot; stock_finger() is the mock's stand-in")
    if design.kind == "imprint":
        return _imprint(part, g)
    p = design.params
    profile = v_profile(p.pad_width_mm, p.groove_angle_deg, p.groove_depth_mm)
    face = p.slack_mm + part.grip_width / 2 - g.stroke_mm  # where the pad face sits with the jaws closed
    jaw_close = seat_distance(part, profile) - face - SQUEEZE_MM
    return _Layout(profile, face, p.tip_height_mm, p.lead_in_mm, jaw_close)


def _imprint(part: Part, g: Gripper) -> _Layout:
    """A pocket shaped like the part, gripping it with the jaws almost closed so it wraps as far as the fingers can
    without touching each other: low fingertips, no lead-in, no slack, as a designer copying the part's shape would draw
    it. A box (or a lying cylinder: a curved cradle isn't modelled) gets a rectangular notch, or a plain flat face where
    a notch as long as the part wouldn't fit beside the gripper. A mesh gets the notch of its bounding box: an
    approximation of a true imprint (planned as its own family), exact only for box-like parts. A section grip gets a flat
    face as long as its span allows: a pocket would need shoulders beside it, where the wider part is."""
    x, y, _ = part.extent_mm
    free_y = g.free_space_mm[1]
    jaw_seat = 2 * SQUEEZE_MM
    notch = y / 2 + IMPRINT_CLEARANCE_MM
    if part.grip_span_mm is not None:
        lo, hi = part.grip_span_mm
        profile = [(max(lo + IMPRINT_CLEARANCE_MM, 1 - free_y), 0.0), (min(hi - IMPRINT_CLEARANCE_MM, free_y - 1), 0.0)]
        return _Layout(profile, part.grip_width / 2 - jaw_seat, tip=1.0, lead=0.0, jaw_close=jaw_seat - SQUEEZE_MM)
    if part.round_from_above:
        profile = _pocket_profile(x / 2 + IMPRINT_CLEARANCE_MM, SEAT_GAP_MM, shoulder=WALL_MM)
    elif notch + WALL_MM + 0.3 <= free_y:
        profile = _notch_profile(notch, x / 2 - SEAT_GAP_MM, shoulder=WALL_MM)
    else:
        profile = [(1 - free_y, 0.0), (free_y - 1, 0.0)]
        return _Layout(profile, x / 2 - jaw_seat, tip=1.0, lead=0.0, jaw_close=jaw_seat - SQUEEZE_MM)
    return _Layout(profile, SEAT_GAP_MM - jaw_seat, tip=1.0, lead=0.0, jaw_close=jaw_seat - SQUEEZE_MM)


def _pocket_profile(radius: float, centre: float, shoulder: float, segments: int = 16) -> Profile:
    """A circular pocket: the circle of this radius around a point `centre` mm in front of the face, cut into the pad."""
    mouth = math.sqrt(radius**2 - centre**2)
    arc = [(py, max(0.0, math.sqrt(max(radius**2 - py**2, 0.0)) - centre)) for py in np.linspace(-mouth, mouth, segments + 1)]
    return [(-mouth - shoulder, 0.0), *arc, (mouth + shoulder, 0.0)]


def _notch_profile(half_width: float, depth: float, shoulder: float, draft: float = 0.3) -> Profile:
    """A rectangular pocket with slightly drafted sides."""
    w = half_width
    return [(-w - draft - shoulder, 0.0), (-w - draft, 0.0), (-w, depth), (w, depth), (w + draft, 0.0), (w + draft + shoulder, 0.0)]


def _finger(part: Part, layout: _Layout, g: Gripper) -> Finger:
    return Finger(
        pieces=[_piece(solid) for solid in _solids(part, layout, g)],
        tip_height_mm=layout.tip,
        jaw_close_mm=layout.jaw_close,
        contact_mm=max(0.0, part.extent_mm[2] - layout.tip - layout.lead),
        friction=g.pad_friction,
        closed_gap_mm=2 * layout.face,
        jaw_open_mm=g.stroke_mm,
        tcp_mm=g.tcp_mm,
        pad_top_mm=_pad_top(part, layout),
    )


def _pad_top(part: Part, layout: _Layout) -> float:
    """The pad reaches from the fingertips to TOP_CLEARANCE_MM above the part it's built for."""
    return part.extent_mm[2] - layout.tip + TOP_CLEARANCE_MM


def _solids(part: Part, layout: _Layout, g: Gripper) -> list[cq.Solid]:
    """The finger's convex solids: pad strips under a bridge under the stock upper blade. The pad reaches from the
    fingertips to above the part, and is thick enough to keep a full wall behind both the deepest groove and the lead-in."""
    profile, face, lead = layout.profile, layout.face, layout.lead
    blade_x, blade_y, blade_z = g.blade_mm
    back = face + max(e for _, e in profile) + lead + WALL_MM
    pad_top = _pad_top(part, layout)
    solids = [_strip(face, back, a, b, pad_top, lead) for a, b in pairwise(profile)]
    half = max(blade_y / 2, -profile[0][0], profile[-1][0])
    blade_bottom = pad_top + BRIDGE_MM
    solids.append(_box((min(0.0, face), max(blade_x, back)), (-half, half), (pad_top, blade_bottom)))
    if blade_bottom < blade_z:
        solids.append(_box((0.0, blade_x), (-blade_y / 2, blade_y / 2), (blade_bottom, blade_z)))
    return solids


def _strip(face: float, back: float, a: tuple[float, float], b: tuple[float, float], top: float, lead: float) -> cq.Solid:
    """The pad between two profile breakpoints, from the fingertips up to `top`, cut along its bottom inner edge by the
    lead-in plane x + z = face + lead."""
    (y0, e0), (y1, e1) = a, b
    strip = cq.Workplane("XY").polyline([(face + e0, y0), (face + e1, y1), (back, y1), (back, y0)]).close().extrude(top)
    if lead > 0:
        c, x0, reach = face + lead, face - 1.0, abs(y0) + abs(y1) + 1.0
        # The region x + z < c as a triangular prism through the strip: drawn in the x-z plane (local y = +z), extruded
        # along -y from y = +reach to y = -reach. Its slanted side, from (c + 1, -1) to (x0, c - x0), is the plane.
        plane = cq.Plane(origin=(0, reach, 0), xDir=(1, 0, 0), normal=(0, -1, 0))
        wedge = cq.Workplane(plane).polyline([(x0, -1.0), (c + 1.0, -1.0), (x0, c - x0)]).close().extrude(2 * reach)
        strip = strip.cut(wedge)
    return strip.val()


def _box(xs: tuple[float, float], ys: tuple[float, float], zs: tuple[float, float]) -> cq.Solid:
    return cq.Solid.makeBox(xs[1] - xs[0], ys[1] - ys[0], zs[1] - zs[0], pnt=cq.Vector(xs[0], ys[0], zs[0]))


def _piece(solid: cq.Solid) -> Piece:
    """A convex solid as the sim server takes it: its corners and outward hull triangles. Every face is planar, so
    tessellation adds no points, and the hull of the corners is the solid exactly."""
    vertices, _ = solid.tessellate(0.01, 0.1)
    return hull_piece([v.toTuple() for v in vertices])


def _hull2d(points: Polygon) -> Polygon:
    """Convex hull, counter-clockwise (Andrew's monotone chain). Fewer than 3 distinct points: no area, so empty."""
    pts = sorted({(round(px, 9), round(py, 9)) for px, py in points})
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


def _boxes_meet(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _overlaps_polygon(a: Polygon, b: Polygon, margin: float = 0.0, eps: float = 1e-9) -> bool:
    """Separating-axis test for two convex polygons; touching doesn't count. With a margin, polygons closer than it along
    every edge normal count as overlapping (slightly generous at corners)."""
    if not a or not b:
        return False
    for poly in (a, b):
        for p, q in zip(poly, poly[1:] + poly[:1], strict=True):
            nx, ny = q[1] - p[1], p[0] - q[0]
            norm = math.hypot(nx, ny)
            if norm == 0:
                continue
            nx, ny = nx / norm, ny / norm
            pa = [nx * px + ny * py for px, py in a]
            pb = [nx * px + ny * py for px, py in b]
            if max(pa) + margin <= min(pb) + eps or max(pb) + margin <= min(pa) + eps:
                return False
    return True
