"""How the part rests on the table (input step 2): a rotation from the CAD frame to the table frame, applied before
every later step. The table frame has z up, the part resting on z = 0 and its footprint centred at x = y = 0.

trimesh's compute_stable_poses() proposes the ways a mesh can rest on a flat surface, each with a likelihood; poses that
look the same from the gripper (same footprint and height, e.g. a cylinder's many side facets) are merged and their
likelihoods summed. "As in the CAD file" is always offered too, for parts whose CAD is already oriented the way they
arrive. A job can cover several stable poses, each with its own grasp, scored by their likelihoods (likely: at least
POSE_CUTOFF; see api/models/job_pose.py). The likelihoods are trimesh's quasi-static estimate, not measured on the cell.

Each stable pose is also turned about z so its footprint's smallest bounding rectangle lines up with x and y, longer
side along x: then 0 and 90 degrees in the grasp step are along the part's own sides.
"""

import math
from typing import Literal

import numpy as np
import trimesh
from pydantic import BaseModel
from scipy.spatial import ConvexHull

from api.models.part_cad import PartMesh, is_round

Rotation = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
IDENTITY: Rotation = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
AS_AUTHORED = "as in the CAD file"
SAME_SIZE_MM = 0.5  # two poses look the same if their footprint and height agree to this, or to SAME_SIZE_FRACTION
SAME_SIZE_FRACTION = 0.02
SQUARE_UP_GAIN = 0.01  # turn a footprint to its smallest bounding rectangle only if that's at least 1% smaller
POSE_CUTOFF = 0.10  # a stable pose at least this likely is "likely": ticked by default when a job covers several poses


class RestingPose(BaseModel):
    rotation: Rotation  # CAD frame -> table frame (before re-centring)
    label: str  # "standing", "on its side", "lying flat", "standing on an end", "lying on its side", "as in the CAD file"
    source: Literal["stable", "as_authored"]
    probability: float | None = None  # likelihood from compute_stable_poses (merged duplicates summed); None for as-authored
    extent_mm: tuple[float, float, float]  # bounding box in the table frame


def resting_poses(mesh: PartMesh, centre_of_mass: tuple[float, float, float], count: int = 4) -> list[RestingPose]:
    """The `count` most likely distinct stable poses, most likely first, then "as in the CAD file". Deterministic: the
    same mesh always gives the same list, so an index into it can be stored."""
    surface = trimesh.Trimesh(mesh.vertices, mesh.triangles, process=False)
    transforms, probabilities = trimesh.poses.compute_stable_poses(surface, center_mass=np.asarray(centre_of_mass, float))
    corners = mesh.vertices[ConvexHull(mesh.vertices).vertices]  # orientation and extents only need the hull's corners
    merged: list[tuple[np.ndarray, tuple[float, float, float], float]] = []  # (rotation, extent, probability)
    for i in sorted(range(len(probabilities)), key=lambda i: -probabilities[i]):
        rotation = _squared_up(np.asarray(transforms[i])[:3, :3], corners)
        extent = _extent(corners @ rotation.T)
        for k, (kept, kept_extent, p) in enumerate(merged):
            if looks_the_same(kept_extent, extent):
                merged[k] = (kept, kept_extent, p + float(probabilities[i]))
                break
        else:
            merged.append((rotation, extent, float(probabilities[i])))
    merged.sort(key=lambda m: -m[2])  # stable: equal likelihoods keep trimesh's order
    poses = [
        RestingPose(
            rotation=_as_tuple(rotation),
            label=_label(corners @ rotation.T, extent),
            source="stable",
            probability=round(p, 4),
            extent_mm=extent,
        )
        for rotation, extent, p in merged[:count]
    ]
    poses.append(RestingPose(rotation=IDENTITY, label=AS_AUTHORED, source="as_authored", extent_mm=_extent(corners)))
    return poses


def is_likely(pose: RestingPose) -> bool:
    return pose.source == "stable" and pose.probability is not None and pose.probability >= POSE_CUTOFF


def is_same_pose(listed: RestingPose, chosen: RestingPose | None) -> bool:
    """Whether a pose from resting_poses() is the part's chosen one. By source and rotation only: a stored "as in the CAD
    file" carries the part's measured extent, rounded differently from the listed one's."""
    return chosen is not None and listed.source == chosen.source and listed.rotation == chosen.rotation


def table_transform(points: np.ndarray, pose: RestingPose | None) -> tuple[np.ndarray, np.ndarray]:
    """(rotation, shift) taking these CAD-frame points (n, 3) to the table frame: p -> rotation @ p + shift, with the
    lowest point on z = 0 and the footprint's bounding box centred. Pass the whole part's points (mesh vertices, or all
    its pieces' corners) and apply the result to anything else (the centre of mass, a pick)."""
    rotation = np.asarray(pose.rotation if pose is not None else IDENTITY, float)
    rotated = np.asarray(points, float) @ rotation.T
    lo, hi = rotated.min(axis=0), rotated.max(axis=0)
    return rotation, -np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])


def to_table_frame(points: np.ndarray, pose: RestingPose | None) -> np.ndarray:
    """CAD-frame points (n, 3) in the table frame: rotated by the pose (none: as authored), lowest point on z = 0,
    footprint centred."""
    rotation, shift = table_transform(points, pose)
    return np.asarray(points, float) @ rotation.T + shift


def _squared_up(rotation: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """The rotation, then a turn about z that lines the footprint's smallest bounding rectangle up with x and y (only if
    that rectangle is clearly smaller, so a round or already square footprint isn't turned), longer side along x."""
    xy = (corners @ rotation.T)[:, :2]
    outline = xy[ConvexHull(xy).vertices]
    as_is = best_area = _box_area(outline, 0.0)
    best = 0.0
    edges = np.diff(np.vstack([outline, outline[:1]]), axis=0)
    for angle in np.arctan2(edges[:, 1], edges[:, 0]):
        turn = -((angle + math.pi / 4) % (math.pi / 2) - math.pi / 4)  # the smallest turn putting this edge along x or y
        area = _box_area(outline, turn)
        if area < best_area - 1e-9:
            best, best_area = turn, area
    turned = _about_z(best if best_area < as_is * (1 - SQUARE_UP_GAIN) else 0.0) @ rotation
    dx, dy, _ = _extent(corners @ turned.T)
    if dy > dx + 1e-6:
        turned = _about_z(math.pi / 2) @ turned
    return turned


def _box_area(xy: np.ndarray, turn: float) -> float:
    c, s = math.cos(turn), math.sin(turn)
    turned = xy @ np.array([[c, s], [-s, c]])
    size = turned.max(axis=0) - turned.min(axis=0)
    return float(size[0] * size[1])


def _about_z(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _extent(points: np.ndarray) -> tuple[float, float, float]:
    return tuple(round(float(v), 4) for v in points.max(axis=0) - points.min(axis=0))


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(SAME_SIZE_MM, SAME_SIZE_FRACTION * max(a, b))


def looks_the_same(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    """Same footprint (either way round) and height: the gripper can't tell the poses apart."""
    return all(_same(x, y) for x, y in zip(sorted(a[:2]), sorted(b[:2]), strict=True)) and _same(a[2], b[2])


def _label(points: np.ndarray, extent: tuple[float, float, float]) -> str:
    """A cylinder stands on an end (round footprint) or lies on its side (round from the side); anything else stands
    (tallest way up, or a cube), lies flat (shortest way up) or is on its side (a plate on its edge)."""
    if is_round(points[:, [0, 1]]):
        return "standing on an end"
    if is_round(points[:, [1, 2]]) or is_round(points[:, [0, 2]]):
        return "lying on its side"
    footprint, height = sorted(extent[:2]), extent[2]
    if (height > footprint[1] and not _same(height, footprint[1])) or all(_same(height, side) for side in footprint):
        return "standing"
    if height < footprint[0] and not _same(height, footprint[0]):
        return "lying flat"
    return "on its side"


def _as_tuple(rotation: np.ndarray) -> Rotation:
    return tuple(tuple(float(v) for v in row) for row in rotation)
