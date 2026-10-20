import math

import pytest

from api.models.offset_grid import OffsetGrid


def held_within(grid: OffsetGrid, radius_mm: float) -> list[bool]:
    return [math.hypot(p["dx"], p["dy"]) <= radius_mm + 1e-9 for p in grid.points()]


def test_points_start_at_the_centre_then_go_round_each_ring_for_each_yaw():
    grid = OffsetGrid(radii_mm=[1, 2], n_directions=4, yaws_deg=[-10, 10])
    points = grid.points()
    assert len(points) == 2 * (1 + 2 * 4)
    assert points[0] == {"dx": 0.0, "dy": 0.0, "yaw_deg": -10}
    assert points[1] == {"dx": 1.0, "dy": 0.0, "yaw_deg": -10}  # first ring, along the closing direction
    assert points[2] == {"dx": 0.0, "dy": 1.0, "yaw_deg": -10}  # then a quarter turn, across it
    assert points[9]["yaw_deg"] == 10


def test_the_default_grid_covers_almost_all_of_a_3_mm_error():
    grid = OffsetGrid()
    assert sum(grid.weights(sigma_mm=3, sigma_deg=8)) == pytest.approx(1, abs=1e-3)


def test_holding_out_to_a_ring_scores_the_chance_the_error_stays_inside_its_cell():
    grid = OffsetGrid(radii_mm=[1, 2, 3, 4, 5, 6])
    # cells end halfway between rings, so holding out to 3 mm covers errors up to 3.5 mm
    expected = 1 - math.exp(-(3.5**2) / (2 * 2**2))
    assert grid.expected_success(held_within(grid, 3), sigma_mm=2, sigma_deg=8) == pytest.approx(expected)


def test_the_same_results_score_lower_at_a_larger_error():
    grid = OffsetGrid()
    held = held_within(grid, 4)
    assert grid.expected_success(held, sigma_mm=1, sigma_deg=8) > grid.expected_success(held, sigma_mm=4, sigma_deg=8)


def test_all_failures_score_zero_and_all_successes_score_the_tested_probability():
    grid = OffsetGrid()
    n = len(grid.points())
    assert grid.expected_success([False] * n, 3, 8) == 0
    assert grid.expected_success([True] * n, 3, 8) == pytest.approx(sum(grid.weights(3, 8)))


def test_zero_error_puts_all_the_weight_on_the_nominal_grasp():
    grid = OffsetGrid(yaws_deg=[-10, 0, 10])
    weights = grid.weights(sigma_mm=0, sigma_deg=0)
    assert weights[grid.per_yaw] == 1  # the centre, at yaw 0
    assert sum(weights) == 1


def test_yaw_levels_split_the_yaw_error_symmetrically():
    grid = OffsetGrid(radii_mm=[1], n_directions=1, yaws_deg=[-10, 0, 10])
    weights = grid.weights(sigma_mm=0, sigma_deg=8)
    low, middle, high = weights[0], weights[grid.per_yaw], weights[2 * grid.per_yaw]
    assert low == pytest.approx(high)
    assert middle == pytest.approx(math.erf(5 / (8 * math.sqrt(2))))  # yaw 0 stands for -5..5 degrees


def test_capture_radius_is_the_last_ring_held_all_the_way_round_at_every_yaw():
    grid = OffsetGrid(radii_mm=[1, 2, 3], n_directions=4, yaws_deg=[-10, 10])
    held = held_within(grid, 2)
    assert grid.capture_radius(held) == 2
    held[grid.per_yaw + 1 + 4] = False  # one miss on the 2 mm ring, at the second yaw
    assert grid.capture_radius(held) == 1
    held[0] = False
    assert grid.capture_radius(held) is None


def test_results_must_match_the_grid():
    with pytest.raises(ValueError):
        OffsetGrid().expected_success([True], sigma_mm=3, sigma_deg=8)


@pytest.mark.parametrize("bad", [{"radii_mm": [2, 1]}, {"radii_mm": [0, 1]}, {"n_directions": 0}, {"yaws_deg": []}])
def test_rejects_an_invalid_grid(bad):
    with pytest.raises(ValueError):
        OffsetGrid(**bad)
