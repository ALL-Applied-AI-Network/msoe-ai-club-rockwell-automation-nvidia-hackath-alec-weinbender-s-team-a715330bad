import math

import pytest

from api.models.error_model import ErrorModel
from api.models.offset_grid import OffsetGrid
from api.models.part import Part
from api.models.piece import hull_piece


def error(sigma_mm: float = 3, sigma_deg: float = 8, **more) -> ErrorModel:
    return ErrorModel(sigma_mm=sigma_mm, sigma_deg=sigma_deg, **more)


def held_within(grid: OffsetGrid, radius_mm: float) -> list[bool]:
    return [math.hypot(p["dx"], p["dy"]) <= radius_mm + 1e-9 for p in grid.points()]


def test_points_start_at_the_centre_then_go_round_each_ring_for_each_yaw():
    grid = OffsetGrid(radii_mm=[1, 2], n_directions=4, yaws_deg=[-10, 10])
    points = grid.points()
    assert len(points) == grid.size == 2 * (1 + 2 * 4)
    assert points[0] == {"dx": 0.0, "dy": 0.0, "yaw_deg": -10}
    assert points[1] == {"dx": 1.0, "dy": 0.0, "yaw_deg": -10}  # first ring, along the closing direction
    assert points[2] == {"dx": 0.0, "dy": 1.0, "yaw_deg": -10}  # then a quarter turn, across it
    assert points[9]["yaw_deg"] == 10


MESH = Part(shape="mesh", pieces=[hull_piece([(x, y, z) for x in (-5, 5) for y in (-3, 3) for z in (0, 4)])])


@pytest.mark.parametrize(
    "part", [Part(shape="box"), Part(diameter_mm=17, length_mm=140, axis="y"), Part(axis="x"), MESH], ids=["box", "lying", "along", "mesh"]
)
def test_parts_that_arent_round_from_above_get_yaw_layers(part):
    grid = OffsetGrid.for_part(part, error(sigma_deg=8))

    assert grid.yaws_deg == [-12, 0, 12]
    assert grid.size == 243 and grid.refined().size == 963
    assert OffsetGrid.for_part(part, error(sigma_deg=0)).yaws_deg == [0], "no yaw error, no yaw layers"


def test_an_upright_cylinder_needs_no_yaw():
    grid = OffsetGrid.for_part(Part(), error(sigma_deg=8))

    assert grid.yaws_deg == [0] and grid.size == 81 and grid.refined().size == 321


def test_the_default_grid_covers_almost_all_of_a_3_mm_error():
    assert sum(OffsetGrid().weights(error())) == pytest.approx(1, abs=1e-3)


def test_holding_out_to_a_ring_scores_the_chance_the_error_stays_inside_its_cell():
    grid = OffsetGrid(radii_mm=[1, 2, 3, 4, 5, 6])
    # cells end halfway between rings, so holding out to 3 mm covers errors up to 3.5 mm
    expected = 1 - math.exp(-(3.5**2) / (2 * 2**2))
    assert grid.expected_success(held_within(grid, 3), error(sigma_mm=2)) == pytest.approx(expected)


def test_the_same_results_score_lower_at_a_larger_error():
    grid = OffsetGrid()
    held = held_within(grid, 4)
    assert grid.expected_success(held, error(sigma_mm=1)) > grid.expected_success(held, error(sigma_mm=4))


def test_all_failures_score_zero_and_all_successes_score_the_tested_probability():
    grid = OffsetGrid()
    assert grid.expected_success([False] * grid.size, error()) == 0
    assert grid.expected_success([True] * grid.size, error()) == pytest.approx(sum(grid.weights(error())))


def test_zero_error_puts_all_the_weight_on_the_nominal_grasp():
    grid = OffsetGrid(yaws_deg=[-10, 0, 10])
    weights = grid.weights(error(sigma_mm=0, sigma_deg=0))
    assert weights[grid.per_yaw] == 1  # the centre, at yaw 0
    assert sum(weights) == 1


def test_yaw_levels_split_the_yaw_error_symmetrically():
    grid = OffsetGrid(radii_mm=[1], n_directions=1, yaws_deg=[-10, 0, 10])
    weights = grid.weights(error(sigma_mm=0, sigma_deg=8))
    low, middle, high = weights[0], weights[grid.per_yaw], weights[2 * grid.per_yaw]
    assert low == pytest.approx(high)
    assert middle == pytest.approx(math.erf(5 / (8 * math.sqrt(2))))  # yaw 0 stands for -5..5 degrees


@pytest.mark.parametrize("sigma", [0.19, 1, 3, 5])
def test_the_bias_quadrature_agrees_with_the_exact_masses_as_the_bias_vanishes(sigma):
    grid = OffsetGrid().refined()
    exact = grid.weights(error(sigma_mm=sigma))
    quadrature = grid.weights(error(sigma_mm=sigma, bias_mm=1e-9))

    assert quadrature == pytest.approx(exact, abs=1e-8)


def test_a_small_bias_keeps_the_mass_but_shifts_it_toward_the_bias():
    grid = OffsetGrid()
    plain = grid.weights(error(sigma_mm=2))
    biased = grid.weights(error(sigma_mm=2, bias_mm=0.5, bias_direction_deg=90))  # toward +y
    points = grid.points()

    assert sum(biased) == pytest.approx(sum(plain), abs=1e-3)
    toward = sum(w for w, p in zip(biased, points, strict=True) if p["dy"] > 0)
    away = sum(w for w, p in zip(biased, points, strict=True) if p["dy"] < 0)
    assert toward > away
    assert sum(w for w, p in zip(plain, points, strict=True) if p["dy"] > 0) == pytest.approx(
        sum(w for w, p in zip(plain, points, strict=True) if p["dy"] < 0)
    )
    ring_2mm = {(p["dx"], p["dy"]): w for p, w in zip(points, biased, strict=True) if abs(math.hypot(p["dx"], p["dy"]) - 2) < 1e-6}
    assert max(ring_2mm, key=ring_2mm.get) == (0.0, 2.0), "the heaviest cell of a ring is the one the bias points at"


def test_a_bias_with_no_spread_lands_on_one_cell():
    grid = OffsetGrid()
    weights = grid.weights(error(sigma_mm=0, sigma_deg=0, bias_mm=3.1, bias_direction_deg=180))

    (heavy,) = [p for p, w in zip(grid.points(), weights, strict=True) if w == 1]
    assert (heavy["dx"], heavy["dy"]) == (-3.0, pytest.approx(0, abs=1e-6))
    assert sum(grid.weights(error(sigma_mm=0, sigma_deg=0, bias_mm=20))) == 0, "off the grid: nothing is tested"


def test_designing_for_a_range_averages_the_weights_over_its_sigmas():
    grid = OffsetGrid(yaws_deg=[-12, 0, 12])
    ranged = error(sigma_range_mm=(1, 4), bias_mm=0.5)

    each = [grid.weights(ranged.at_sigma(sigma)) for sigma in ranged.sigmas_mm]
    assert len(each) == 6
    assert grid.weights(ranged) == pytest.approx([sum(ws) / len(ws) for ws in zip(*each, strict=True)])


def test_capture_radius_is_the_last_ring_held_all_the_way_round_at_every_yaw():
    grid = OffsetGrid(radii_mm=[1, 2, 3], n_directions=4, yaws_deg=[-10, 10])
    held = held_within(grid, 2)
    assert grid.capture_radius(held) == 2
    held[grid.per_yaw + 1 + 4] = False  # one miss on the 2 mm ring, at the second yaw
    assert grid.capture_radius(held) == 1
    held[0] = False
    assert grid.capture_radius(held) is None


def test_the_curve_scores_one_result_at_each_reported_sigma():
    grid = OffsetGrid()
    curve = grid.curve(held_within(grid, 4), error(bias_mm=1))

    assert list(curve) == ["0.5", "1", "2", "3", "4", "5"]
    values = list(curve.values())
    assert values == sorted(values, reverse=True) and values[0] == pytest.approx(1, abs=1e-6)
    assert curve["3"] == pytest.approx(grid.expected_success(held_within(grid, 4), error(sigma_mm=3, bias_mm=1)))


def test_the_preview_draws_the_error_around_its_bias():
    grid = OffsetGrid()
    preview = grid.preview(error(sigma_mm=2, bias_mm=1, bias_direction_deg=90))

    assert len(preview.points) == preview.n_offsets == 81
    assert [p.weight for p in preview.points] == pytest.approx(grid.weights(error(sigma_mm=2, bias_mm=1, bias_direction_deg=90)))
    assert [(c.label, c.radius_mm) for c in preview.circles] == [("1σ", 2), ("2σ", 4)]
    assert preview.circles[0].centre_mm == pytest.approx((0, 1))
    assert (preview.outer_ring_mm, preview.covered_to_mm, preview.yaws_deg) == (12, 13, [0])
    assert preview.coverage == pytest.approx(sum(p.weight for p in preview.points))
    assert preview.warnings == []


def test_a_bias_and_spread_reaching_past_the_outer_ring_is_warned_about():
    warnings = OffsetGrid().warnings(error(sigma_mm=5, bias_mm=3))

    assert warnings == ["bias + 2σ (13.0 mm) reaches past the 12 mm outer ring: errors beyond the grid count as misses"]
    assert OffsetGrid().warnings(error(sigma_range_mm=(1, 6.5))) != [], "a range is judged by its largest sigma"


def test_results_must_match_the_grid():
    with pytest.raises(ValueError):
        OffsetGrid().expected_success([True], error())


@pytest.mark.parametrize("bad", [{"radii_mm": [2, 1]}, {"radii_mm": [0, 1]}, {"n_directions": 0}, {"yaws_deg": []}])
def test_rejects_an_invalid_grid(bad):
    with pytest.raises(ValueError):
        OffsetGrid(**bad)


def test_a_job_over_several_poses_tests_yaw_unless_every_pose_is_round_from_above():
    upright, lying = Part(), Part(axis="y")

    assert OffsetGrid.for_parts([upright], error()) == OffsetGrid.for_part(upright, error()) == OffsetGrid()
    assert OffsetGrid.for_parts([upright, lying], error()).yaws_deg == OffsetGrid.for_part(lying, error()).yaws_deg == [-12, 0, 12]
    assert OffsetGrid.for_parts([upright, upright], error()).yaws_deg == [0]
