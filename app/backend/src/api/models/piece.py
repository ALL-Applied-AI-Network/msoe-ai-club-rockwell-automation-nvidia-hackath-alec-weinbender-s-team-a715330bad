"""A convex piece: the shape physics engines collide fast and reliably. Fingers and mesh parts both travel to the sim as
lists of pieces, in millimetres.

A convex piece stays convex under any rigid motion, so a part's pieces are computed once (V-HACD, in the CAD frame) and
only transformed for each resting pose and grasp axis afterwards.
"""

from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel
from scipy.spatial import ConvexHull

Point = tuple[float, float, float]


class Piece(BaseModel):
    """A convex solid: the hull of its points. The triangles are its faces, wound counter-clockwise seen from outside."""

    points: list[Point]
    triangles: list[tuple[int, int, int]]


def hull_piece(points) -> Piece:
    """The convex hull of some points, as a Piece: its corners and outward triangles. Raises scipy's QhullError if the
    points are flat or on a line."""
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


def transform_pieces(pieces: Sequence[Piece], rotation, translation=(0.0, 0.0, 0.0)) -> list[Piece]:
    """Each piece moved rigidly: p -> rotation @ p + translation. A proper rotation keeps the triangles' winding."""
    r, t = np.asarray(rotation, float), np.asarray(translation, float)
    return [
        Piece(points=[tuple(float(v) for v in r @ np.asarray(p, float) + t) for p in piece.points], triangles=list(piece.triangles))
        for piece in pieces
    ]


def pieces_bounds(pieces: Sequence[Piece]) -> tuple[np.ndarray, np.ndarray]:
    """The axis-aligned bounding box of all the pieces: (min xyz, max xyz)."""
    points = np.array([p for piece in pieces for p in piece.points], float)
    return points.min(axis=0), points.max(axis=0)
