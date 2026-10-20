import math

import numpy as np
import pytest
from scipy.spatial import ConvexHull

from api.models.part_cad import MAX_PIECE_VERTICES, is_round, measure, merge_vertices


@pytest.fixture(scope="module")
def tessellated(shapes):
    """tessellated(name) -> (vertices, triangles, volume) of a test part, straight from CadQuery (no file)."""

    def of(name):
        solid = shapes[name].val()
        vertices, triangles = solid.tessellate(0.05, 0.2)
        return np.array([v.toTuple() for v in vertices]), np.array(triangles), solid.Volume()

    return of


def bounds(pieces):
    points = np.array([p for piece in pieces for p in piece.points])
    return points.min(axis=0), points.max(axis=0)


def test_a_smooth_convex_part_is_one_piece_thinned_to_the_vertex_limit(tessellated):
    vertices, triangles, volume = tessellated("glass_tube")

    measured, mesh = measure("tube.step", "step", vertices, triangles, volume)

    (piece,) = measured.pieces
    assert len(ConvexHull(vertices).vertices) > MAX_PIECE_VERTICES and len(piece.points) <= MAX_PIECE_VERTICES
    lo, hi = bounds(measured.pieces)
    assert (lo, hi) == (pytest.approx(mesh.vertices.min(axis=0)), pytest.approx(mesh.vertices.max(axis=0)))  # exact extents
    assert ConvexHull(np.array(piece.points)).volume == pytest.approx(volume, rel=0.01)


def test_a_concave_part_is_split_and_its_pieces_reach_the_real_surface(tessellated):
    vertices, triangles, volume = tessellated("vial_cap")

    measured, mesh = measure("cap.step", "step", vertices, triangles, volume)

    assert 1 < len(measured.pieces) <= 16
    assert all(len(piece.points) <= MAX_PIECE_VERTICES for piece in measured.pieces)
    lo, hi = bounds(measured.pieces)
    assert lo == pytest.approx(mesh.vertices.min(axis=0), abs=0.01) and hi == pytest.approx(mesh.vertices.max(axis=0), abs=0.01)
    hull = ConvexHull(np.array([p for piece in measured.pieces for p in piece.points])).volume
    assert hull == pytest.approx(math.pi * 15.875**2 * 15.7, rel=0.01)  # the pieces' hull is the cylinder


def test_the_l_brackets_pieces_add_up_to_its_volume(tessellated):
    vertices, triangles, volume = tessellated("l_bracket")

    measured, _ = measure("bracket.step", "step", vertices, triangles, volume)

    total = sum(ConvexHull(np.array(piece.points)).volume for piece in measured.pieces)
    assert total == pytest.approx(volume, rel=0.05)


def test_the_part_is_centred_on_the_table_and_its_fit_recognises_a_tube_along_x(tessellated):
    vertices, triangles, volume = tessellated("glass_tube")

    measured, mesh = measure("tube.step", "step", vertices + 100, triangles, volume)

    lo, hi = mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)
    assert lo[2] == pytest.approx(0) and (lo[:2] + hi[:2]) == pytest.approx((0, 0), abs=1e-9)
    assert measured.centre_of_mass_mm == pytest.approx((0, 0, 8.5), abs=0.01)
    assert measured.fit == "lying cylinder"
    assert (measured.suggested.axis, measured.suggested.length_mm) == ("x", pytest.approx(140))


def test_repeated_vertices_are_merged():
    square = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 0, 0], [1, 1, 0], [0, 1, 0]], float)

    vertices, triangles = merge_vertices(square, np.array([[0, 1, 2], [3, 4, 5]]))

    assert len(vertices) == 4 and vertices[triangles].tolist() == square.reshape(2, 3, 3).tolist()


def test_round_outlines():
    angles = np.linspace(0, 2 * math.pi, 64, endpoint=False)
    circle = np.column_stack([np.cos(angles), np.sin(angles)]) * 10

    assert is_round(circle)
    assert not is_round(np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float))
    assert not is_round(circle * [1, 1.2])


def test_a_file_without_solid_geometry_is_refused():
    with pytest.raises(ValueError, match="no solid geometry"):
        measure("empty.stl", "stl", np.zeros((3, 3)), np.array([[0, 1, 2]]), 0.0)
