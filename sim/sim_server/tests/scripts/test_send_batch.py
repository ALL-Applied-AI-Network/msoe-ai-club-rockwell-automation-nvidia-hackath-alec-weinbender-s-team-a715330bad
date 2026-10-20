"""scripts/send_batch.py: its offset grid must be the app's default grid (same points, same order)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "send_batch.py"


@pytest.fixture(scope="module")
def send_batch():
    spec = importlib.util.spec_from_file_location("send_batch", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grid_is_the_apps_81_points(send_batch):
    grid = send_batch.grid_offsets()
    assert len(grid) == 81
    assert grid[0] == {"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}
    assert grid[1] == {"dx": 1.0, "dy": 0.0, "yaw_deg": 0.0}  # r = 1 mm, direction 0: +dx, toward JawL
    assert grid[3] == pytest.approx({"dx": 0.0, "dy": 1.0, "yaw_deg": 0.0})  # direction 2: +dy
    assert grid[-1]["dx"] == pytest.approx(12 * 0.5**0.5) and grid[-1]["dy"] == pytest.approx(-12 * 0.5**0.5)
    assert len(send_batch.grid_offsets(yaws=(-10.0, 0.0, 10.0))) == 243


def test_grid_map_draws_rings(send_batch):
    held = [True] + [True] * 8 + [False] * 72
    lines = send_batch.grid_map(held, 1)
    assert lines[0].endswith("#") and lines[1].endswith("########") and lines[-1].endswith("........")
