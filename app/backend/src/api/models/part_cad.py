"""A part read from a CAD file: measured, matched to the cylinder or box the optimizer understands, and split into convex
pieces for the simulator.

Everything here is in the CAD frame: the file as authored, in millimetres (an STL in inches is scaled before it gets
here), set on the table (lowest point at z = 0) and centred in x and y. The resting pose and the grasp axis are applied
later (resting_pose.py, grasp.py). Physics engines collide convex shapes fast and reliably, so the part is split into
convex pieces with V-HACD, each kept within PhysX's 64-vertex hull limit, in the same form as a finger's pieces. Convex
pieces stay convex under rigid motion, so they're computed once, here, and only transformed afterwards.
"""

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import vhacdx
from pydantic import BaseModel
from scipy.spatial import ConvexHull, QhullError

from api.models.material import Material
from api.models.part import Part
from api.models.piece import Piece, hull_piece

ROUND_TOLERANCE = 0.03  # a footprint counts as round if its two extents agree to 3% and it fills a circle to 3%
CONVEX_TOLERANCE = 0.005  # a part whose hull is within 0.5% of its volume is convex
MAX_PIECES = 16
MAX_PIECE_VERTICES = 64  # PhysX's limit for a convex hull
VHACD_RESOLUTION = 100_000  # voxels in the bounding box


class PartCad(BaseModel):
    """What a CAD file says about the part, in the CAD frame."""

    filename: str
    source: Literal["step", "stl"]
    extent_mm: tuple[float, float, float]  # bounding box along x, y and z, as authored: shown so a units mistake is caught
    volume_mm3: float
    centre_of_mass_mm: tuple[float, float, float]  # uniform density
    face_types: dict[str, int] = {}  # STEP only: OpenCascade surface types and how many faces have each, e.g. {"PLANE": 6}
    material_hint: Material | None = None  # STEP only: the material the file names, if any (most name none)
    fit: str  # which shape the file matches as authored: "standing cylinder", "lying cylinder" or "box"
    suggested: Part  # that shape, sized from the file; the real one comes from the resting pose and grasp axis
    pieces: list[Piece]  # convex pieces, in mm, in the CAD frame


@dataclass(frozen=True)
class PartMesh:
    """The part's surface mesh in the CAD frame: vertices (n, 3) in mm, triangles (m, 3) indexing them."""

    vertices: np.ndarray
    triangles: np.ndarray


def measure(
    filename: str,
    source: Literal["step", "stl"],
    vertices: np.ndarray,
    triangles: np.ndarray,
    volume: float,
    *,
    centre_of_mass: tuple[float, float, float] | None = None,
    face_types: dict[str, int] | None = None,
    material_hint: Material | None = None,
) -> tuple[PartCad, PartMesh]:
    """vertices (n, 3) in mm and triangles (m, 3) index into them: the part's surface mesh, as read from the file.
    centre_of_mass is in the file's coordinates (the B-rep's, for a STEP); without one it's taken from the mesh."""
    if len(vertices) < 4 or len(triangles) < 4:
        raise ValueError(f"{filename}: no solid geometry found")
    vertices, triangles = merge_vertices(np.asarray(vertices, float), np.asarray(triangles))
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    shift = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
    centred = vertices - shift
    com = (np.asarray(centre_of_mass, float) if centre_of_mass is not None else mesh_centre_of_mass(vertices, triangles)) - shift
    dx, dy, dz = (float(v) for v in hi - lo)
    fit, suggested = _fit(centred, dx, dy, dz)
    measured = PartCad(
        filename=filename,
        source=source,
        extent_mm=(dx, dy, dz),
        volume_mm3=abs(float(volume)),
        centre_of_mass_mm=tuple(float(v) for v in com),
        face_types=face_types or {},
        material_hint=material_hint,
        fit=fit,
        suggested=suggested,
        pieces=convex_pieces(centred, triangles, abs(float(volume))),
    )
    return measured, PartMesh(centred, np.asarray(triangles))


def mesh_centre_of_mass(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """The centroid of a closed mesh's solid (signed tetrahedra from the origin); the vertex mean if it encloses nothing."""
    a, b, c = (vertices[triangles[:, k]] for k in range(3))
    volumes = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6
    total = volumes.sum()
    if abs(total) < 1e-9:
        return vertices.mean(axis=0)
    return ((a + b + c) / 4 * volumes[:, None]).sum(axis=0) / total


def merge_vertices(vertices: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One vertex per position (to 1e-6 mm). Tessellated B-rep faces repeat their shared edges' vertices, which leaves a
    closed solid looking like loose patches to anything that follows its edges."""
    unique, inverse = np.unique(np.round(vertices, 6), axis=0, return_inverse=True)
    return unique, inverse.reshape(-1)[triangles]


def convex_pieces(vertices: np.ndarray, triangles: np.ndarray, volume: float) -> list[Piece]:
    """The part as convex pieces. A part that's already convex is one piece: its hull, thinned to the vertex limit if a
    curved surface gave it more corners (a 32-sided tube is within 1% of a round one). Anything else goes through
    approximate convex decomposition (V-HACD): a handful of hulls that cover it, each within the vertex limit. V-HACD
    builds its hulls from voxels, which leaves them up to a voxel inside the real surface, so each one takes in the
    surface vertices within a voxel of it. Degenerate (flat) hulls are dropped."""
    hull = ConvexHull(vertices)
    if hull.volume <= volume * (1 + CONVEX_TOLERANCE):
        return [hull_piece(_thinned(vertices[hull.vertices]))]
    hulls = vhacdx.compute_vhacd(
        np.ascontiguousarray(vertices, dtype=np.float64),
        # vhacdx takes VTK-style faces: a flat list of [3, a, b, c] per triangle
        np.column_stack((np.full(len(triangles), 3), triangles)).ravel().astype(np.uint32),
        maxConvexHulls=MAX_PIECES,
        maxNumVerticesPerCH=MAX_PIECE_VERTICES,
        resolution=VHACD_RESOLUTION,
        maxRecursionDepth=6,  # at most 64 splits before merging down to MAX_PIECES: half the time of the default 10
        minimumVolumePercentErrorAllowed=1.0,
    )
    voxel = float(np.prod(vertices.max(axis=0) - vertices.min(axis=0)) / VHACD_RESOLUTION) ** (1 / 3)
    pieces = []
    for points, _ in hulls:
        try:
            pieces.append(hull_piece(_thinned(_snapped(points, vertices, voxel))))
        except QhullError:  # all points on a plane or a line
            continue
    if not pieces:
        raise ValueError("convex decomposition found no solid pieces; is the mesh closed?")
    return pieces


def _snapped(points: np.ndarray, surface: np.ndarray, margin: float) -> np.ndarray:
    """A piece's corners plus the part's surface vertices within `margin` of it: its hull grown out to the real surface."""
    planes = ConvexHull(points).equations  # outward normals and offsets: n . p + d <= 0 inside
    near = np.all(surface @ planes[:, :3].T + planes[:, 3] <= margin, axis=1)
    merged = np.vstack([points, surface[near]])
    return merged[ConvexHull(merged).vertices]


def _thinned(points: np.ndarray, limit: int = MAX_PIECE_VERTICES) -> np.ndarray:
    """At most `limit` of a hull's corners, spread evenly (farthest-point sampling), starting from the six that set its
    bounding box, so the piece keeps its exact extents."""
    if len(points) <= limit:
        return points
    chosen = sorted({int(i) for axis in range(3) for i in (points[:, axis].argmin(), points[:, axis].argmax())})
    distance = np.min(np.linalg.norm(points[:, None, :] - points[chosen][None, :, :], axis=2), axis=1)
    while len(chosen) < limit:
        i = int(distance.argmax())
        chosen.append(i)
        distance = np.minimum(distance, np.linalg.norm(points - points[i], axis=1))
    return points[chosen]


def _fit(vertices: np.ndarray, dx: float, dy: float, dz: float) -> tuple[str, Part]:
    """A standing cylinder if the footprint is a circle; a lying cylinder if the side view along y (axis across the jaws)
    or along x (axis along them) is; otherwise a box."""
    if _round(vertices[:, [0, 1]], dx, dy):
        return "standing cylinder", Part(shape="cylinder", diameter_mm=(dx + dy) / 2, length_mm=dz, axis="z")
    if _round(vertices[:, [0, 2]], dx, dz):
        return "lying cylinder", Part(shape="cylinder", diameter_mm=(dx + dz) / 2, length_mm=dy, axis="y")
    if _round(vertices[:, [1, 2]], dy, dz):
        return "lying cylinder", Part(shape="cylinder", diameter_mm=(dy + dz) / 2, length_mm=dx, axis="x")
    return "box", Part(shape="box", width_mm=dx, depth_mm=dy, height_mm=dz)


def is_round(points: np.ndarray) -> bool:
    """Whether 2-D points (n, 2) outline a circle: their two extents agree, and their hull fills that circle, both to 3%."""
    a, b = points.max(axis=0) - points.min(axis=0)
    return _round(points, float(a), float(b))


def _round(points: np.ndarray, a: float, b: float) -> bool:
    d = (a + b) / 2
    if d <= 0 or abs(a - b) > ROUND_TOLERANCE * d:
        return False
    fill = ConvexHull(points).volume / (math.pi * d * d / 4)  # a 2-D hull's "volume" is its area
    return abs(fill - 1) <= ROUND_TOLERANCE
