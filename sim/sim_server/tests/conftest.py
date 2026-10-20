"""Shared fixtures. These tests never start Isaac Sim: they use only the twin's pure-Python modules (scene_config,
gripper_geometry, ik, fk) from the repo's sim/fanuc_er4ia_sim, the way the server imports them."""

import pytest

from sim_server.models.gripper import GripperGeometry
from sim_server.robot.gripper_frame import geometry_from_twin
from sim_server.twin import use_twin

use_twin()  # at import time, so test modules can import the twin's modules


@pytest.fixture(scope="session")
def geo() -> GripperGeometry:
    return geometry_from_twin()


def _box_piece(x0, x1, y0, y1, z0, z1):
    """An axis-aligned box as (points, outward triangles)."""
    points = [((x0, x1)[i & 1], (y0, y1)[(i >> 1) & 1], (z0, z1)[(i >> 2) & 1]) for i in range(8)]
    quads = [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4), (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]
    return points, [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]


@pytest.fixture
def box_piece():
    """box_piece(x0, x1, y0, y1, z0, z1) -> (points, outward triangles). Test modules can't import conftest directly."""
    return _box_piece
