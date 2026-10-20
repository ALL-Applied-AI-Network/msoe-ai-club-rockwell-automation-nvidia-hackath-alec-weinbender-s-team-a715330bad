"""scripts/send_batch.py: its offset grid must be the app's default grid (same points, same order); overrides, reports
and run comparison work with contract v2's fields."""

import importlib.util
import json
import logging
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


def test_overrides_replace_the_files_settings(send_batch):
    batch = {"designs": [], "offsets": [], "grip_force_n": 15, "transport": None}
    assert send_batch.apply_overrides(batch, None, None) == batch
    assert send_batch.apply_overrides(batch, "none", "fast") == {"designs": [], "offsets": [], "grip_force_n": None, "transport": "fast"}
    assert send_batch.apply_overrides(batch, "2.5", "none")["grip_force_n"] == 2.5
    assert batch["grip_force_n"] == 15  # the file's batch isn't modified


def run(tmp_path, name, held, in_hand=None, after=None, offsets=None):
    offsets = offsets or [{"dx": 0, "dy": 0, "yaw_deg": 0}, {"dx": 1, "dy": 0, "yaw_deg": 0}]
    response = {"held": held, "in_hand": in_hand, "held_after_transport": after, "sim": {"envs": 1}}
    path = tmp_path / name
    path.write_text(json.dumps({"elapsed_s": 1.0, "request": {"designs": [{"id": "stock"}], "offsets": offsets}, "response": response}))
    return path


def test_compare_checks_held_and_transport_and_reports_in_hand(send_batch, tmp_path, caplog):
    a = run(tmp_path, "a.json", [[True, True]], [[[0.1, 0.0, 0.0, 1.0, 179.0], [1.0, 0.0, 0.0, 0.0, 0.0]]], [[True, True]])
    b = run(tmp_path, "b.json", [[True, True]], [[[0.3, 0.0, 0.0, 1.5, -179.0], None]], [[True, True]])
    with caplog.at_level(logging.INFO, logger="send_batch"):
        assert send_batch.compare(a, b) == 0  # held agrees; in-hand only reported
    assert "In-hand differences over 1 grasps" in caplog.text and "yaw 2.00 / 2.00" in caplog.text  # the short way round
    lost = run(tmp_path, "c.json", [[True, True]], None, [[True, False]])
    assert send_batch.compare(a, lost) == 1  # held after transport disagrees at offset 1
    old = run(tmp_path, "d.json", [[True, True]])  # a v1 run: no in_hand, no transport
    assert send_batch.compare(old, a) == 0


def test_in_hand_differences_skip_grasps_one_run_dropped(send_batch):
    diffs = send_batch.in_hand_differences([[[1, 2, 3, 4, 5], None]], [[[1.5, 2, 3, 4, 5], [0, 0, 0, 0, 0]]])
    assert diffs == [[0.5], [0], [0], [0], [0]]
    assert send_batch.in_hand_differences(None, [[None]]) == [[], [], [], [], []]


def test_report_prints_in_hand_and_transport(send_batch, caplog):
    batch = {"designs": [{"id": "pad"}], "offsets": [{"dx": 0, "dy": 0, "yaw_deg": 0}, {"dx": 3, "dy": 0, "yaw_deg": 0}]}
    response = {
        "held": [[True, False]],
        "in_hand": [[[0.0, 0.5, 0.1, 0.0, 2.0], None]],
        "held_after_transport": [[False, False]],
        "sim": {"envs": 1},
    }
    with caplog.at_level(logging.INFO, logger="send_batch"):
        send_batch.report(batch, response, None)
    assert "held 1/2, after transport 0" in caplog.text
    assert "dy   0.50" in caplog.text and "lost in transport" in caplog.text
    assert 'Sim: {"envs": 1}' in caplog.text
    assert "offset median 0.51 mm" in send_batch.in_hand_summary(response["in_hand"][0])
