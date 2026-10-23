"""The grasp axis (input step 5): which horizontal direction the jaws close along, checked by geometry alone in
seconds, after the cell profile is confirmed (its stroke and free space decide what fits).

Angles and points are in the table frame (resting_pose.py): angle_deg is the closing direction measured from +x toward
+y, and 0 and 180 are the same axis. posed_part() turns the chosen grasp into the Part the fingers and the sim see: the
table frame rotated by -angle about z and shifted so the grasp centre is the origin.

How a direction is judged (docs/notes/input-flow-backend-plan.md, 4.2), with u the closing direction and v across it:

- width: the part's extent along u, over the part above the fingertips (z >= 1 mm, or the locked grip height);
- contact patches: the faces within max(0.3 mm, 2% of the width) of each extreme along u whose normals lie inside the
  friction cone (within atan(mu) of +-u): what a flat pad touches first, and can push on without slipping;
- centre: midway between the extremes along u; along v, the centre of mass, clamped to where both patches are, so the
  jaws don't twist the part (com_offset_mm is how far it had to move).

A pad can only touch what's at the extremes, so everything here works on the triangles near them; no ray casting is
needed except for face picks and the internal-grip check.

A section grasp grips part of the part: a stretch along v that's clearly narrower than the whole part along u (a screw's
shank beside its head, an L-bracket's arm). Its pads sit within that stretch (span_mm), so they never meet the wider
material, and it's judged exactly like a whole-part direction on the slab of the part between the stretch's ends: the
pads touch what's at the extremes of the slab. Proposals rank whole-part directions as they always have; when the part
has sections, sections and whole-part directions are ranked together by verdict (ok, then warn, then blocked), then the
narrower width (less stroke, and the pads close across the part rather than along it), then the larger contact area.
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy.spatial import ConvexHull, QhullError
from trimesh.intersections import slice_faces_plane

from api.models.cell_profile import Gripper
from api.models.part import Part
from api.models.part_cad import PartMesh, is_round
from api.models.part_record import PartRecord
from api.models.piece import Piece, transform_pieces
from api.models.resting_pose import RestingPose, looks_the_same, resting_poses, table_transform

Verdict = Literal["ok", "warn", "blocked"]

MIN_TIP_MM = 1.0  # the fingertips stay this far above the table, so only the part above it can be gripped
MIN_CONTACT_MM2 = 1.0  # each contact patch needs at least this much area
BAND_MM, BAND_FRACTION = 0.3, 0.02  # a face touches if it's within max(BAND_MM, BAND_FRACTION x width) of an extreme
PARALLEL_DEG = 2.0  # parallel flat faces: both patches flat and opposed within this
FLAT_DEG = 1.0  # a patch is flat if all its faces are within this of its mean normal
SKEW_WARNING_DEG = 10.0
OFF_CENTRE_MM, OFF_CENTRE_FRACTION = 2.0, 0.10  # warn when the grip is further than max(2 mm, 10% of the depth) off the CoM
SIDE_FACE_MAX_NZ = 0.7  # a picked face must face sideways: |n_z| below this
SAME_GRASP_DEG = 10.0  # proposals closer than this are the same grasp
MAX_CANDIDATES = 3
BOX_TOLERANCE = 0.02  # a hull within 2% of its bounding box is a box
CYLINDER_TOLERANCE = 0.03  # a round silhouette whose hull is within 3% of pi r^2 L is a cylinder
PRIMITIVE_CENTRE_MM = 0.5  # a box or cylinder must be centred on the grasp; gripped off-centre it's sent as a mesh
HOLLOW_FRACTION = 0.6  # an internal grip needs the part's volume under 60% of its hull's
MIN_FEATURE_MM = 2.0  # a narrower feature must be at least this tall
TABLE_SLOP_MM = 0.05  # piece corners this close below the table are put on it
WIDER_BELOW_MM = 0.5  # a grip height over a base wider than this is refused (the pads are sized to the whole part)
SECTION_STEP_MM = 0.5  # the width profile along v is sampled this finely
SECTION_ANGLE_STEP = 5  # sections are looked for every 5 degrees
SECTION_NARROWER_MM, SECTION_NARROWER_FRACTION = 1.0, 0.15  # a section is narrower than the whole part by at least this
SECTION_MIN_MM = 4.0  # and at least this long along v: a 2 mm pad and a margin each side
SECTION_PLATEAU_MM, SECTION_PLATEAU_FRACTION = 0.5, 0.10  # a section's width varies by at most this over it
SECTION_MIN_CONTACT_MM = 2.0  # the pads touch it along at least this much of v
VERDICT_RANK = {"ok": 0, "warn": 1, "blocked": 2}
ROUND_NOTE = "round from above: any direction works"
LAST_RESORT = "needs a longer-stroke gripper or a suction cup"


class GraspPick(BaseModel):
    """A face the user clicked on the 3D view (three.js raycast against the table-frame mesh)."""

    point: tuple[float, float, float]
    normal: tuple[float, float, float]


class GraspCandidate(BaseModel):
    """One grasp axis and how it scored. verdict: "blocked" if the fingers can't reach around it or a jaw would find no
    face to push on; "warn" for faces far from parallel, an off-centre grip or a pick the jaws wouldn't touch first; else
    "ok". The stock-fingers warning doesn't change the verdict: it's about the stock baseline, not this grasp."""

    angle_deg: float  # closing direction, 0..180
    centre_mm: tuple[float, float]  # where the jaws centre, table frame
    # A section grasp: where along v (across the jaws), from the centre, the pads may sit without meeting the wider part
    # beside it. None: the whole part.
    span_mm: tuple[float, float] | None = None
    width_mm: float  # the part's extent along the closing direction (the section's, for a section grasp)
    depth_mm: float  # and across it
    contact_area_mm2: float  # the smaller of the two contact patches
    opposition_deg: float  # how far the two contact faces are from pointing straight at each other
    parallel_faces: bool  # both patches flat and opposed within 2 degrees
    com_offset_mm: float  # how far the grab is from the centre of mass, across the jaws
    fits: bool  # the custom fingers can reach around it (stroke, free space)
    stock_fits: bool  # the stock fingers open wide enough (else the stock baseline scores 0)
    verdict: Verdict
    warnings: list[str] = []
    blocked_reasons: list[str] = []
    note: str | None = None  # e.g. "round from above: any direction works"


class NothingFits(BaseModel):
    reason: str  # exactly why, with numbers: "narrowest width 87.0 mm; these fingers reach around at most 83.0 mm"
    suggestions: list[str]  # in order: offset fingers, another resting pose, a narrower feature, an internal grip; else a
    # longer-stroke gripper or a suction cup


class GraspProposals(BaseModel):
    candidates: list[GraspCandidate]  # the top 1 to 3, best first
    rejected: list[str]  # one line per reason, with counts: "174 directions too wide (narrowest 31.7 mm)"
    nothing_fits: NothingFits | None = None


class GraspChoice(BaseModel):
    """The grasp a job uses. Auto: an accepted proposal; manual: the user's angle or face picks, after the same checks."""

    angle_deg: float = Field(ge=0, lt=360)
    centre_mm: tuple[float, float] = (0.0, 0.0)
    span_mm: tuple[float, float] | None = None  # a section grasp's span (GraspCandidate.span_mm); None: the whole part
    source: Literal["auto", "manual"] = "auto"
    grip_height_mm: float | None = Field(None, gt=0)  # locks tip_height_mm in every family; None: the optimizer chooses
    picks: list[GraspPick] = []  # the faces clicked, for a manual grasp (logged)


def reach_mm(gripper: Gripper) -> float:
    """The widest part custom fingers can reach around: each pad sits at most free space x out from the centre, less its
    wall and the minimum slack (83 mm for the UWM CSI cell)."""
    # Imported here, not at the top: search_space works with the job models (job_spec imports this module).
    from api.models.finger import WALL_MM
    from api.models.search_space import MIN_SLACK_MM

    return 2 * (gripper.free_space_mm[0] - WALL_MM - MIN_SLACK_MM)


def table_mesh(record: PartRecord, mesh: PartMesh, pose: RestingPose | None = None) -> tuple[PartMesh, tuple[float, float, float]]:
    """The part's surface mesh (its CAD-frame PartMesh, as stored with the record) and centre of mass in the table frame
    of `pose`: by default the record's chosen pose, or as authored while none is chosen. What propose_grasps(),
    check_grasp() and the 3D view work on."""
    rotation, shift = table_transform(mesh.vertices, pose or record.pose)
    centre = rotation @ np.asarray(record.measured.centre_of_mass_mm, float) + shift
    return PartMesh(mesh.vertices @ rotation.T + shift, mesh.triangles), tuple(float(c) for c in centre)


def propose_grasps(mesh: PartMesh, centre_of_mass: tuple[float, float, float], friction: float, gripper: Gripper) -> GraspProposals:
    """Auto proposal: sweep closing directions over the table-frame mesh and rank the ones that work, with the part's
    sections (module docstring) when it has any. friction is the static coefficient against the pad (the friction cone's
    half-angle is atan of it)."""
    reach, com = reach_mm(gripper), np.asarray(centre_of_mass, float)
    surface = _surface(mesh, friction, MIN_TIP_MM)
    if surface is None:
        return GraspProposals(candidates=[], rejected=[], nothing_fits=_nothing_fits(mesh, com, friction, gripper, [], []))
    if is_round(surface.outline):
        contact = _contact(surface, 0.0)
        if contact.failure(reach) is None:
            return GraspProposals(candidates=[_candidate(contact, com, gripper, reach, note=ROUND_NOTE)], rejected=[])
    contacts = [_contact(surface, float(angle)) for angle in range(180)]
    failures = [contact.failure(reach) for contact in contacts]
    rejected = _rejections(contacts, failures, friction, reach)
    sections = _section_candidates(mesh, surface, com, friction, gripper, reach)
    if all(failures) and not sections:
        return GraspProposals(
            candidates=[], rejected=rejected, nothing_fits=_nothing_fits(mesh, com, friction, gripper, contacts, failures)
        )
    best = [max(group, key=lambda c: c.contact_area) for group in _groups(contacts, failures)]
    best.sort(key=lambda c: (not c.parallel, -round(c.contact_area, 6), round(c.width, 6), c.angle))
    chosen: list[_Contact] = []
    for contact in best:
        if all(_axis_gap(contact.angle, other.angle) >= SAME_GRASP_DEG for other in chosen):
            chosen.append(contact)
    whole = [_candidate(c, com, gripper, reach) for c in chosen]
    candidates = _ranked(whole + sections) if sections else whole
    return GraspProposals(candidates=candidates[:MAX_CANDIDATES], rejected=rejected)


def check_grasp(
    mesh: PartMesh,
    centre_of_mass: tuple[float, float, float],
    friction: float,
    gripper: Gripper,
    *,
    angle_deg: float | None = None,
    picks: list[GraspPick] = (),
    grip_height_mm: float | None = None,
    centre_mm: tuple[float, float] | None = None,
    span_mm: tuple[float, float] | None = None,
) -> GraspCandidate:
    """A manual choice (an angle, or one or two face picks), checked like a proposal: blocked if it can't fit, a warning if
    it's risky. One pick sets the angle from the face's horizontal normal, and a ray from it along -n finds the face
    opposite; two picks set it from the line between them. The grip goes through the picks, and they're checked against
    where the jaws touch first; when they lie on a section (module docstring), the grasp grips that section. With an
    angle as well (a manual GraspChoice carries both), the angle sets the direction and the picks only place the grip. A
    grip height lifts the fingertips, so only the part above it counts. A section grasp chosen before (an angle with its
    centre_mm and span_mm) is checked on that same section. Raises ValueError for input that doesn't set a direction."""
    picks = list(picks)
    if angle_deg is None and not picks:
        raise ValueError("give an angle or one or two face picks")
    if span_mm is not None and (angle_deg is None or centre_mm is None):
        raise ValueError("a section grasp needs its angle and centre")
    if len(picks) > 2:
        raise ValueError("pick one face, or two points to grip between")
    reach, com = reach_mm(gripper), np.asarray(centre_of_mass, float)
    top = float(mesh.vertices[:, 2].max())
    floor = max(MIN_TIP_MM, grip_height_mm or 0.0)
    surface = _surface(mesh, friction, floor) if floor < top else None
    if surface is None:
        raise ValueError(f"nothing to grip above {floor:g} mm: the part is {top:.1f} mm tall")
    points = [np.asarray(pick.point, float) for pick in picks]
    blocked, opposite = [], None
    if angle_deg is not None:
        angle = float(angle_deg)
    elif len(picks) == 1:
        normal = np.asarray(picks[0].normal, float)
        normal = normal / (np.linalg.norm(normal) or 1.0)
        if abs(normal[2]) >= SIDE_FACE_MAX_NZ or not np.any(normal[:2]):
            raise ValueError("pick a side face: the jaws close sideways, and that face points up or down")
        inward = np.array([-normal[0], -normal[1], 0.0]) / np.linalg.norm(normal[:2])
        angle = math.degrees(math.atan2(normal[1], normal[0]))
        start = points[0] + 1e-3 * inward
        hits = _ray_hits(start, inward, mesh.vertices[mesh.triangles])
        if len(hits):
            opposite = start + hits.max() * inward  # where the material ends on the far side, along the closing line
        else:
            blocked.append("no material opposite the picked face along the closing direction")
    else:
        line = points[1][:2] - points[0][:2]
        if np.linalg.norm(line) < 0.5:
            raise ValueError("the two picks are too close together to set a direction")
        angle = math.degrees(math.atan2(line[1], line[0]))
    angle = round(angle % 180, 1) % 180
    _, v = _axes(angle)
    target = float(np.mean([p[:2] @ v for p in points])) if points else None
    span = None
    if span_mm is not None:
        centre_v = float(np.asarray(centre_mm, float) @ v)
        span, target = (centre_v + span_mm[0], centre_v + span_mm[1]), centre_v
    elif target is not None:
        span = next((s for s in _sections(surface, angle) if s[0] <= target <= s[1]), None)
    contact = _contact(surface, angle) if span is None else _section_contact(mesh, friction, floor, angle, span)
    if contact is None:
        raise ValueError(f"nothing to grip in that section above {floor:g} mm")
    if floor > MIN_TIP_MM and (whole := _surface(mesh, friction, MIN_TIP_MM, None if span is None else (v, *span))) is not None:
        full = _contact(whole, contact.angle).width
        if full > contact.width + WIDER_BELOW_MM:
            # The grasp step looks only above the grip height, but the V-pad's pads are sized to the part's whole width
            # (posed_part, finger.py), so the job would be blocked at step 6 with fingers that miss the gripped section.
            blocked.append(
                f"gripping above a wider base isn't supported yet: the part is {full:.1f} mm wide below the grip height and "
                f"{contact.width:.1f} mm above it, and the fingers are sized to its whole width"
            )
    risks = []
    for point, what in [(p, "the picked point") for p in points] + (
        [(opposite, "the face opposite the pick")] if opposite is not None else []
    ):
        along = float(point[:2] @ contact.u)
        gap = contact.hi - along if along >= (contact.lo + contact.hi) / 2 else along - contact.lo
        if gap > contact.band:
            risks.append(f"the jaws first touch the part {gap:.1f} mm further out than {what}")
    risks += [f"the picked point is below the fingertips: they stay {floor:g} mm up" for p in points if p[2] < floor - 1e-6]
    if span is not None and (contact.overlap is None or contact.overlap[1] - contact.overlap[0] < SECTION_MIN_CONTACT_MM):
        blocked.append(f"the pads would touch the section along less than {SECTION_MIN_CONTACT_MM:g} mm")
    return _candidate(contact, com, gripper, reach, target_v=target, risks=risks, blocked=blocked, span=span)


def posed_part(
    record: PartRecord, grasp: GraspChoice, pad_friction: tuple[float, float], mesh: PartMesh | None = None, pose: RestingPose | None = None
) -> Part:
    """The part as the gripper meets it: resting pose (`pose`, by default the record's chosen one), then -angle about z,
    then the grasp centre to the origin.
    Classified by its convex hull as a box, a cylinder (axis z, y or x) or a mesh of the transformed pieces; mass and
    friction from the record. The pieces were split once, in the CAD frame, and are only moved here. A primitive is
    centred on the grasp by definition, so a grip off its centre (a manual pick near one end) is sent as a mesh. Raises
    ValueError while the part has no mass (no material and no measured mass).

    Pass the part's CAD-frame `mesh` (services/parts.py: load_mesh) so the table frame is set exactly as table_mesh()
    sets it, which is where grasp.centre_mm was measured. Without it the frame is set from the pieces' own bounds,
    which can sit a fraction of a millimetre inside the real surface."""
    mass = record.confirmed_mass_g
    if mass is None:
        raise ValueError("the part has no mass yet: choose its material (or enter a density) or enter a measured mass")
    pieces = record.measured.pieces
    corners = np.array([p for piece in pieces for p in piece.points], float)
    rotation, shift = table_transform(mesh.vertices if mesh is not None else corners, pose or record.pose)
    turn = _about_z(-math.radians(grasp.angle_deg))
    rotation, shift = turn @ rotation, turn @ (shift - np.array([*grasp.centre_mm, 0.0]))
    friction = record.friction(pad_friction)
    grip = {}
    if grasp.span_mm is not None:
        if mesh is not None:
            vertices, triangles = np.asarray(mesh.vertices, float), np.asarray(mesh.triangles)
        else:
            vertices = corners
            triangles = np.concatenate([np.asarray(p.triangles) + sum(len(q.points) for q in pieces[:i]) for i, p in enumerate(pieces)])
        grip = {"grip_width_mm": _section_width(vertices @ rotation.T + shift, triangles, grasp.span_mm), "grip_span_mm": grasp.span_mm}
    shape = _primitive(corners @ rotation.T + shift)
    if shape is not None and not grip:
        return Part(**shape, mass_g=mass, friction=friction)
    return Part(shape="mesh", pieces=_on_table(transform_pieces(pieces, rotation, shift)), mass_g=mass, friction=friction, **grip)


def _section_width(vertices: np.ndarray, triangles: np.ndarray, span: tuple[float, float]) -> float:
    """The width along x of the part (grasp-frame vertices) between y = span[0] and span[1]: what a section grip closes on."""
    for sign, at in ((1.0, span[0]), (-1.0, span[1])):
        vertices, triangles, _ = slice_faces_plane(vertices, triangles, plane_normal=[0.0, sign, 0.0], plane_origin=[0.0, at, 0.0])
        if len(triangles) == 0:
            raise ValueError("the grasp's section misses the part")
    used = vertices[np.unique(triangles)]
    return float(np.ptp(used[:, 0]))


def _on_table(pieces: list[Piece]) -> list[Piece]:
    """The pieces with any corner a hair below the table (V-HACD hulls snapped to the surface, rounding) put on it: the
    sim server rejects a mesh part that reaches below z = 0."""
    return [
        Piece(points=[(x, y, 0.0 if -TABLE_SLOP_MM < z < 0 else z) for x, y, z in piece.points], triangles=piece.triangles)
        for piece in pieces
    ]


@dataclass
class _Surface:
    """The part's surface above the fingertips, in the table frame, ready for sweeping."""

    outline: np.ndarray  # (k, 2) the convex hull of its footprint: all a width needs
    solid: np.ndarray  # (n, 3, 3) every triangle above the floor: what a width profile needs
    corners: np.ndarray  # (m, 3, 3) the triangles that could face a jaw (their normal tilts less than the cone from level)
    normals: np.ndarray  # (m, 3) unit, outward
    areas: np.ndarray  # (m,)
    faces: np.ndarray  # (m,) which flat face each triangle is part of (coplanar triangles share an id)
    cos_cone: float  # cos(atan(mu))


@dataclass
class _Contact:
    """One closing direction: the extremes along u, and the patches a flat pad touches there (+u side, then -u)."""

    angle: float
    cone_deg: float  # the friction cone's half-angle
    u: np.ndarray
    v: np.ndarray
    lo: float
    hi: float
    depth: float
    band: float
    areas: tuple[float, float]
    spans: tuple[tuple[float, float], tuple[float, float]]  # each patch's extent along v
    normals: tuple[np.ndarray, np.ndarray]  # each patch's mean normal (zero if there's no patch)
    flat: tuple[bool, bool]
    faces: tuple[int, int]  # each patch's largest flat face (-1: no patch)

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def contact_area(self) -> float:
        return min(self.areas)

    @property
    def overlap(self) -> tuple[float, float] | None:
        """Where both patches are, along v."""
        lo, hi = max(self.spans[0][0], self.spans[1][0]), min(self.spans[0][1], self.spans[1][1])
        return (lo, hi) if lo <= hi + 1e-6 else None

    @property
    def opposition(self) -> float:
        if self.contact_area <= 0:
            return 180.0
        return math.degrees(math.acos(float(np.clip(-self.normals[0] @ self.normals[1], -1.0, 1.0))))

    @property
    def parallel(self) -> bool:
        return all(self.flat) and self.opposition <= PARALLEL_DEG

    def failure(self, reach: float) -> Literal["wide", "cone", "apart"] | None:
        """The first rule this direction fails: too wide, no face in the friction cone at an extreme, or patches that
        don't overlap across the jaws."""
        if self.width > reach + 1e-9:
            return "wide"
        if self.contact_area < MIN_CONTACT_MM2:
            return "cone"
        return "apart" if self.overlap is None else None


def _surface(mesh: PartMesh, friction: float, floor: float, slab: tuple[np.ndarray, float, float] | None = None) -> _Surface | None:
    """The mesh above `floor` (and, for a section, between a and b along the unit vector v of slab = (v, a, b)), with
    what a sweep needs precomputed. None if nothing solid is left."""
    vertices, triangles, _ = slice_faces_plane(
        np.asarray(mesh.vertices, float), np.asarray(mesh.triangles), plane_normal=[0.0, 0.0, 1.0], plane_origin=[0.0, 0.0, floor]
    )
    if slab is not None:
        v, a, b = slab
        for sign, at in ((1.0, a), (-1.0, b)):
            if len(triangles) == 0:
                break
            vertices, triangles, _ = slice_faces_plane(
                vertices, triangles, plane_normal=[sign * v[0], sign * v[1], 0.0], plane_origin=[at * v[0], at * v[1], 0.0]
            )
    if len(triangles) == 0:
        return None
    try:
        footprint = vertices[np.unique(triangles)][:, :2]
        outline = footprint[ConvexHull(footprint).vertices]
    except QhullError:  # a sliver or a line: nothing to grip
        return None
    corners = solid = vertices[triangles]
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    double_area = np.linalg.norm(cross, axis=1)
    normals = cross / np.where(double_area > 0, double_area, 1.0)[:, None]
    cos_cone = 1 / math.sqrt(1 + friction**2)
    keep = (double_area > 1e-9) & (np.linalg.norm(normals[:, :2], axis=1) >= cos_cone - 1e-9)
    corners, normals, areas = corners[keep], normals[keep], double_area[keep] / 2
    planes = np.column_stack([np.round(normals * 100), np.round(np.einsum("ij,ij->i", normals, corners[:, 0]) * 10)])
    faces = np.unique(planes, axis=0, return_inverse=True)[1].reshape(-1) if len(planes) else np.zeros(0, int)
    return _Surface(outline=outline, solid=solid, corners=corners, normals=normals, areas=areas, faces=faces, cos_cone=cos_cone)


def _axes(angle: float) -> tuple[np.ndarray, np.ndarray]:
    """u (the closing direction) and v (across the jaws) at this angle."""
    theta = math.radians(angle)
    return np.array([math.cos(theta), math.sin(theta)]), np.array([-math.sin(theta), math.cos(theta)])


def _width_profile(surface: _Surface, angle: float) -> tuple[np.ndarray, np.ndarray]:
    """(v, width): the part's extent along u where the plane at each v cuts it, every SECTION_STEP_MM along v; NaN where
    the plane misses it. From where every triangle's edges cross each plane, so long triangles (a turned shank's sides)
    count along their whole length."""
    u, v = _axes(angle)
    fu, fv = surface.solid[:, :, :2] @ u, surface.solid[:, :, :2] @ v
    lo, hi = float(fv.min()), float(fv.max())
    centres = np.arange(lo + SECTION_STEP_MM / 2, hi, SECTION_STEP_MM)
    c = centres[:, None]
    low, high = np.full((len(centres), len(fu)), np.inf), np.full((len(centres), len(fu)), -np.inf)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a, b = fv[:, i], fv[:, j]
        crosses = ((a - c) * (b - c) <= 0) & (a != b)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = fu[:, i] + (c - a) / (b - a) * (fu[:, j] - fu[:, i])
        low, high = np.where(crosses, np.minimum(low, at), low), np.where(crosses, np.maximum(high, at), high)
    widths = high.max(axis=1) - low.min(axis=1)
    return centres, np.where(np.isfinite(widths), widths, np.nan)


def _sections(surface: _Surface, angle: float) -> list[tuple[float, float]]:
    """The stretches (a, b) along v where the part is clearly narrower along u than at its widest, and long enough for a
    pad. Each is trimmed to its plateau (the longest run within SECTION_PLATEAU of its median width), so a flare toward
    the wider part (a countersunk head's cone) stays outside it: the pads would touch the flare first. The ends are the
    outermost sampled planes inside, so a pad within the stretch stays off the wider part."""
    centres, widths = _width_profile(surface, angle)
    if not np.isfinite(widths).any():
        return []
    whole = float(np.nanmax(widths))
    limit = whole - max(SECTION_NARROWER_MM, SECTION_NARROWER_FRACTION * whole)
    out = []
    for run in _runs(np.isfinite(widths) & (widths <= limit)):
        typical = float(np.median(widths[run]))
        level = typical + max(SECTION_PLATEAU_MM, SECTION_PLATEAU_FRACTION * typical)
        plateau = max(_runs(widths[run] <= level), key=len, default=None)
        if plateau is None:
            continue
        a, b = float(centres[run][plateau[0]]), float(centres[run][plateau[-1]])
        if b - a >= SECTION_MIN_MM:
            out.append((a, b))
    return out


def _runs(flags: np.ndarray) -> list[np.ndarray]:
    """The index runs where flags is True."""
    out, start = [], None
    for i, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            out.append(np.arange(start, i))
            start = None
    return out


def _section_contact(mesh: PartMesh, friction: float, floor: float, angle: float, span: tuple[float, float]) -> _Contact | None:
    """The direction judged on the slab of the part between span = (a, b) along v: what pads within it touch."""
    _, v = _axes(angle)
    surface = _surface(mesh, friction, floor, slab=(v, *span))
    return None if surface is None else _contact(surface, angle)


def _section_target(contact: _Contact, span: tuple[float, float], com: np.ndarray) -> float:
    """Where along v a section grasp centres: on the centre of mass if it's inside the span with room for a pad either
    side, else the span's middle (then clamped to where both patches are, by _candidate)."""
    com_v, half_pad = float(com[:2] @ contact.v), SECTION_MIN_CONTACT_MM / 2
    return com_v if span[0] + half_pad <= com_v <= span[1] - half_pad else (span[0] + span[1]) / 2


def _section_candidates(
    mesh: PartMesh, surface: _Surface, com: np.ndarray, friction: float, gripper: Gripper, reach: float
) -> list[GraspCandidate]:
    """Every section that works, one per SECTION_ANGLE_STEP direction and stretch: the pads touch it along at least
    SECTION_MIN_CONTACT_MM and the direction passes the same rules as a whole-part one."""
    out = []
    for angle in range(0, 180, SECTION_ANGLE_STEP):
        for span in _sections(surface, float(angle)):
            contact = _section_contact(mesh, friction, MIN_TIP_MM, float(angle), span)
            if contact is None or contact.failure(reach) is not None:
                continue
            overlap = contact.overlap
            if overlap is None or overlap[1] - overlap[0] < SECTION_MIN_CONTACT_MM:
                continue
            out.append(_candidate(contact, com, gripper, reach, target_v=_section_target(contact, span, com), span=span))
    return out


def _ranked(candidates: list[GraspCandidate]) -> list[GraspCandidate]:
    """Whole-part and section candidates together, best first (the rule is in the module docstring), one per axis."""
    ordered = sorted(candidates, key=lambda c: (VERDICT_RANK[c.verdict], round(c.width_mm, 1), -c.contact_area_mm2, c.angle_deg))
    chosen: list[GraspCandidate] = []
    for candidate in ordered:
        if all(_axis_gap(candidate.angle_deg, other.angle_deg) >= SAME_GRASP_DEG for other in chosen):
            chosen.append(candidate)
    return chosen


def _contact(surface: _Surface, angle: float) -> _Contact:
    theta = math.radians(angle)
    u, v = np.array([math.cos(theta), math.sin(theta)]), np.array([-math.sin(theta), math.cos(theta)])
    along, across = surface.outline @ u, surface.outline @ v
    lo, hi = float(along.min()), float(along.max())
    band = max(BAND_MM, BAND_FRACTION * (hi - lo))
    fu, fv = surface.corners[:, :, :2] @ u, surface.corners[:, :, :2] @ v
    nu = surface.normals[:, :2] @ u
    sides = []
    for sign, extreme in ((1.0, hi), (-1.0, -lo)):
        level = extreme - band
        near = (sign * nu >= surface.cos_cone) & ((sign * fu).max(axis=1) >= level)
        fraction, v_lo, v_hi = _above(sign * fu[near], fv[near], level)
        weights = surface.areas[near] * fraction * (sign * nu[near])  # as the pad sees it: largest when square to it
        touching = weights > 1e-9
        if not touching.any():
            sides.append((0.0, (math.inf, -math.inf), np.zeros(3), False, -1))
            continue
        normals, weights = surface.normals[near][touching], weights[touching]
        mean = (weights[:, None] * normals).sum(axis=0)
        mean /= np.linalg.norm(mean)
        ids, inverse = np.unique(surface.faces[near][touching], return_inverse=True)
        sides.append(
            (
                float(weights.sum()),
                (float(v_lo[touching].min()), float(v_hi[touching].max())),
                mean,
                bool(np.all(normals @ mean >= math.cos(math.radians(FLAT_DEG)))),
                int(ids[np.bincount(inverse.reshape(-1), weights).argmax()]),
            )
        )
    (a1, s1, n1, f1, i1), (a2, s2, n2, f2, i2) = sides
    return _Contact(
        angle=angle,
        cone_deg=math.degrees(math.acos(surface.cos_cone)),
        u=u,
        v=v,
        lo=lo,
        hi=hi,
        depth=float(across.max() - across.min()),
        band=band,
        areas=(a1, a2),
        spans=(s1, s2),
        normals=(n1, n2),
        flat=(f1, f2),
        faces=(i1, i2),
    )


def _above(f: np.ndarray, g: np.ndarray, level: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For triangles with linear values f and g at their corners (k, 3): the fraction of each one's area where f >= level,
    and the range of g over that part (from its corners above the level and where its edges cross it)."""
    f0, f1, f2 = np.sort(f, axis=1).T
    with np.errstate(divide="ignore", invalid="ignore"):
        tip = (f2 - level) ** 2 / ((f2 - f0) * (f2 - f1))  # the level cuts off a small triangle at the top corner
        most = 1 - (level - f0) ** 2 / ((f2 - f0) * (f1 - f0))  # ... or at the bottom one, the rest is above
        fraction = np.where(level <= f0, 1.0, np.where(level >= f2, 0.0, np.where(level >= f1, tip, most)))
        values = [np.where(f >= level, g, np.nan)]
        for i, j in ((0, 1), (1, 2), (2, 0)):
            crosses = (f[:, i] - level) * (f[:, j] - level) < 0
            t = np.where(crosses, (level - f[:, i]) / (f[:, j] - f[:, i]), np.nan)
            values.append((g[:, i] + t * (g[:, j] - g[:, i]))[:, None])
        stacked = np.hstack(values)
    return fraction, np.nanmin(stacked, axis=1), np.nanmax(stacked, axis=1)


def _candidate(
    contact: _Contact,
    com: np.ndarray,
    gripper: Gripper,
    reach: float,
    *,
    target_v: float | None = None,
    risks: list[str] = (),
    blocked: list[str] = (),
    note: str | None = None,
    span: tuple[float, float] | None = None,
) -> GraspCandidate:
    """The candidate for one direction: centred between the extremes along u and, along v, at the target (the centre of
    mass, or the picks) clamped to where both patches are. span: a section grasp's stretch (a, b) along v, which the
    candidate gives relative to its centre."""
    com_v = float(com[:2] @ contact.v)
    want = com_v if target_v is None else target_v
    overlap = contact.overlap
    centre_v = want if overlap is None else min(max(want, overlap[0]), overlap[1])
    centre = contact.u * (contact.lo + contact.hi) / 2 + contact.v * centre_v
    off = abs(com_v - centre_v)
    fits, stock_fits = contact.width <= reach + 1e-9, contact.width < gripper.stock_tip_gap_mm
    blocked, risks = list(blocked), list(risks)
    if not fits:
        blocked.append(f"{contact.width:.1f} mm across at {contact.angle:g}°; these fingers reach around at most {reach:.1f} mm")
    if contact.contact_area < MIN_CONTACT_MM2:
        blocked.append(
            f"no face at one of the extremes is within {contact.cone_deg:.1f}° of the closing direction (the friction cone): "
            "a jaw would have nothing to push on"
        )
    elif overlap is None:
        blocked.append("the faces the jaws touch don't overlap across the jaws: gripping would twist the part")
    if contact.contact_area >= MIN_CONTACT_MM2 and contact.opposition > SKEW_WARNING_DEG:
        risks.append(f"the contact faces are {contact.opposition:.0f}° from parallel: the part may twist or squeeze out")
    if off > max(OFF_CENTRE_MM, OFF_CENTRE_FRACTION * contact.depth):
        risks.append(f"the grip is {off:.1f} mm from the centre of mass, across the jaws: the part may tip as it's lifted")
    warnings = risks + (
        [] if stock_fits else [f"the stock fingers open at most {gripper.stock_tip_gap_mm:g} mm, so the stock baseline will score 0"]
    )
    return GraspCandidate(
        angle_deg=round(contact.angle, 1),
        centre_mm=(round(float(centre[0]), 3), round(float(centre[1]), 3)),
        span_mm=None if span is None else (round(span[0] - centre_v, 3), round(span[1] - centre_v, 3)),
        width_mm=round(contact.width, 3),
        depth_mm=round(contact.depth, 3),
        contact_area_mm2=round(contact.contact_area, 2),
        opposition_deg=round(contact.opposition, 2),
        parallel_faces=contact.parallel,
        com_offset_mm=round(off, 3),
        fits=fits,
        stock_fits=stock_fits,
        verdict="blocked" if blocked else "warn" if risks else "ok",
        warnings=warnings,
        blocked_reasons=blocked,
        note=note,
    )


def _groups(contacts: list[_Contact], failures: list[str | None]) -> list[list[_Contact]]:
    """Neighbouring kept directions (1 degree apart, wrapping from 179 to 0) that touch the same largest face on each
    side are one grasp."""
    parent = list(range(len(contacts)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, contact in enumerate(contacts):
        j = (i + 1) % len(contacts)
        if failures[i] is None and failures[j] is None and -1 not in contact.faces:
            following = contacts[j].faces if j else contacts[j].faces[::-1]  # past 179 degrees the +u and -u sides swap
            if contact.faces == following:
                parent[root(j)] = root(i)
    groups: dict[int, list[_Contact]] = {}
    for i, contact in enumerate(contacts):
        if failures[i] is None:
            groups.setdefault(root(i), []).append(contact)
    return list(groups.values())


def _axis_gap(a: float, b: float) -> float:
    """Degrees between two closing axes (0 and 180 are the same axis)."""
    gap = abs(a - b) % 180
    return min(gap, 180 - gap)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _rejections(contacts: list[_Contact], failures: list[str | None], friction: float, reach: float) -> list[str]:
    """One line per rule, counting the directions that failed it first."""
    out = []
    wide = [c for c, f in zip(contacts, failures, strict=True) if f == "wide"]
    if wide:
        narrowest = min(wide, key=lambda c: c.width)
        out.append(
            f"{_count(len(wide), 'direction')} too wide (narrowest {narrowest.width:.1f} mm at {narrowest.angle:g}°; "
            f"these fingers reach around at most {reach:.1f} mm)"
        )
    if cone := failures.count("cone"):
        out.append(
            f"{_count(cone, 'direction')} without a face inside the friction cone at both extremes "
            f"(μ {friction:g}: faces must be within {math.degrees(math.atan(friction)):.1f}° of the closing direction)"
        )
    if apart := failures.count("apart"):
        out.append(f"{_count(apart, 'direction')} where the faces the jaws touch don't overlap across the jaws")
    return out


def _nothing_fits(
    mesh: PartMesh, com: np.ndarray, friction: float, gripper: Gripper, contacts: list[_Contact], failures: list[str | None]
) -> NothingFits:
    """Why no direction works, with numbers, and what would, each suggestion backed by a check on this part."""
    reach = reach_mm(gripper)
    top = float(mesh.vertices[:, 2].max())
    if not contacts:
        reason = f"the part is only {top:.1f} mm tall, and the fingertips stay at least {MIN_TIP_MM:g} mm above the table"
    elif all(f == "wide" for f in failures):
        narrowest = min(contacts, key=lambda c: c.width)
        reason = f"narrowest width {narrowest.width:.1f} mm (at {narrowest.angle:g}°); these fingers reach around at most {reach:.1f} mm"
    elif "apart" not in failures:
        reason = (
            f"no direction narrow enough to grip has a face within {math.degrees(math.atan(friction)):.1f}° of the closing "
            f"direction at both extremes (the friction cone for μ {friction:g})"
        )
    else:
        reason = "no direction narrow enough to grip has contact faces that overlap across the jaws"
    found = [
        _offset_fingers(contacts, failures, gripper, reach),
        _other_pose(mesh, com, friction, reach),
        _narrower_feature(mesh, friction, reach),
        _internal_grip(mesh, com),
    ]
    return NothingFits(reason=reason, suggestions=[s for s in found if s] or [LAST_RESORT])


def _offset_fingers(contacts: list[_Contact], failures: list[str | None], gripper: Gripper, reach: float) -> str | None:
    """Pads set further out, if only the reach stops a direction that has good faces to grip."""
    good = [c for c, f in zip(contacts, failures, strict=True) if f == "wide" and c.failure(math.inf) is None]
    if not good:
        return None
    narrowest = min(good, key=lambda c: c.width)
    need = narrowest.width / 2 + gripper.free_space_mm[0] - reach / 2
    return (
        f"offset fingers: at {narrowest.angle:g}° the part is {narrowest.width:.1f} mm across with good faces to grip; pads set "
        f"out that far need {need:.1f} mm of free space beside each jaw, and this cell profile allows {gripper.free_space_mm[0]:g} mm. "
        "If the cell has the room, raise its free space"
    )


def _other_pose(mesh: PartMesh, com: np.ndarray, friction: float, reach: float) -> str | None:
    """The most likely other stable pose in which some direction fits, by name."""
    here = tuple(float(v) for v in mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0))
    for pose in resting_poses(mesh, tuple(com)):
        if pose.source != "stable" or looks_the_same(pose.extent_mm, here):
            continue
        rotation, shift = table_transform(mesh.vertices, pose)
        surface = _surface(PartMesh(mesh.vertices @ rotation.T + shift, mesh.triangles), friction, MIN_TIP_MM)
        if surface is None:
            continue
        fitting = [c for c in (_contact(surface, float(a)) for a in range(0, 180, 2)) if c.failure(reach) is None]
        if fitting:
            best = max(fitting, key=lambda c: c.contact_area)
            x, y, z = pose.extent_mm
            return (
                f'another resting pose: "{pose.label}" (step 2; {x:.1f} x {y:.1f} mm footprint, {z:.1f} mm tall), where it is '
                f"{best.width:.1f} mm across at its best axis, which these fingers reach"
            )
    return None


def _narrower_feature(mesh: PartMesh, friction: float, reach: float) -> str | None:
    """A top section narrow enough to grip, from horizontal sections: the lowest grip height above which some direction
    fits (the pads run straight up from the fingertips, so everything above them must fit too)."""
    vertices = np.asarray(mesh.vertices, float)
    top = float(vertices[:, 2].max())
    if top - MIN_TIP_MM < 2 * MIN_FEATURE_MM:
        return None
    edges = np.unique(np.sort(np.asarray(mesh.triangles)[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2), axis=1), axis=0)
    a, b = vertices[edges[:, 0]], vertices[edges[:, 1]]
    directions = np.radians(np.arange(180))
    directions = np.column_stack([np.cos(directions), np.sin(directions)])
    step = max(0.5, (top - MIN_TIP_MM) / 60)
    for level in np.arange(MIN_TIP_MM + step, top - MIN_FEATURE_MM + 1e-9, step):
        crossing = (a[:, 2] - level) * (b[:, 2] - level) < 0
        t = (level - a[crossing, 2]) / (b[crossing, 2] - a[crossing, 2])
        cut = a[crossing, :2] + t[:, None] * (b[crossing, :2] - a[crossing, :2])
        section = np.vstack([vertices[vertices[:, 2] >= level, :2], cut])
        try:
            section = section[ConvexHull(section).vertices]
        except QhullError:
            continue
        along = section @ directions.T
        widths = along.max(axis=0) - along.min(axis=0)
        fitting = [int(i) for i in np.argsort(widths, kind="stable")[:5] if widths[i] <= reach]
        surface = _surface(mesh, friction, float(level)) if fitting else None
        for angle in fitting if surface is not None else []:
            contact = _contact(surface, float(angle))
            if contact.failure(reach) is None:
                return (
                    f"a narrower feature: z {level:.0f}-{top:.0f} mm is {contact.width:.1f} mm wide (at {angle}°), from a "
                    f"grip height of {level:.1f} mm; gripping it needs fingers sized to that feature, which the V-pad family "
                    "doesn't do yet (its pads are sized to the whole part)"
                )
    return None


def _internal_grip(mesh: PartMesh, com: np.ndarray) -> str | None:
    """Fingers inside a hollow part, opening outward: the part is under 60% of its hull's volume and has a walled
    opening at the top, over its centre of mass."""
    vertices = np.asarray(mesh.vertices, float)
    corners = vertices[mesh.triangles]
    volume = float(np.einsum("ij,ij->i", corners[:, 0], np.cross(corners[:, 1], corners[:, 2])).sum() / 6)
    hull = ConvexHull(vertices).volume
    if volume >= HOLLOW_FRACTION * hull:
        return None
    top, height = float(vertices[:, 2].max()), float(np.ptp(vertices[:, 2]))
    start = np.array([com[0], com[1], top + 1.0])
    hits = _ray_hits(start, np.array([0.0, 0.0, -1.0]), corners)
    depth = height if not len(hits) else float(hits.min()) - 1.0
    if depth < max(MIN_FEATURE_MM, 0.25 * height):
        return None
    inside = np.array([com[0], com[1], top - depth / 2])
    walls = [(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0)]
    if not all(len(_ray_hits(inside, np.array(d), corners)) for d in walls):
        return None  # open at the side too: there's no wall all round to push against
    return (
        f"an internal grip: the part is hollow and open at the top ({depth:.1f} mm deep at its centre; its volume is "
        f"{100 * volume / hull:.0f}% of its hull's), so fingers inside it, opening outward, could hold it. That's not one of "
        "the built finger families yet"
    )


def _ray_hits(origin: np.ndarray, direction: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Distances along a ray to every triangle (corners (m, 3, 3)) it crosses: Möller-Trumbore, all triangles at once."""
    a, e1, e2 = corners[:, 0], corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-12
    inverse = np.where(ok, 1 / np.where(ok, det, 1.0), 0.0)
    s = origin - a
    bu = np.einsum("ij,ij->i", s, p) * inverse
    q = np.cross(s, e1)
    bv = (q @ direction) * inverse
    t = np.einsum("ij,ij->i", e2, q) * inverse
    return t[ok & (bu >= 0) & (bv >= 0) & (bu + bv <= 1) & (t > 1e-9)]


def _primitive(points: np.ndarray) -> dict | None:
    """The box or cylinder these grasp-frame points' hull is, if it is one and the grasp is at its centre."""
    lo, hi = points.min(axis=0), points.max(axis=0)
    size = hi - lo
    if np.abs((lo[:2] + hi[:2]) / 2).max() > PRIMITIVE_CENTRE_MM:
        return None
    volume = ConvexHull(points).volume
    if volume >= (1 - BOX_TOLERANCE) * float(np.prod(size)):
        return {"shape": "box", "width_mm": float(size[0]), "depth_mm": float(size[1]), "height_mm": float(size[2])}
    for axis, view, along in (("z", [0, 1], 2), ("y", [0, 2], 1), ("x", [1, 2], 0)):
        if is_round(points[:, view]):
            diameter, length = float(size[view].mean()), float(size[along])
            ideal = math.pi * diameter**2 / 4 * length
            if abs(volume - ideal) <= CYLINDER_TOLERANCE * ideal:
                return {"shape": "cylinder", "diameter_mm": diameter, "length_mm": length, "axis": axis}
    return None


def _about_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
