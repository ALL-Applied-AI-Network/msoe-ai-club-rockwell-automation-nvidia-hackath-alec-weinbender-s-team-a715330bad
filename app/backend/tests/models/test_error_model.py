import math

import pytest

from api.models.error_model import CURVE_SIGMAS_MM, PRESETS, RANGE_SIGMAS, ErrorModel


def test_presets_fill_in_the_numbers_and_only_the_twin_is_measured():
    model = ErrorModel.from_preset("calibrated")

    assert (model.preset, model.sigma_mm, model.sigma_deg) == ("calibrated", 1.0, 3.0)
    assert [name for name, preset in PRESETS.items() if not preset.placeholder] == ["twin"]
    assert {(p.sigma_mm, p.sigma_deg) for p in PRESETS.values()} == {(0.19, 0.5), (1.0, 3.0), (3.0, 8.0), (5.0, 12.0)}


def test_the_bias_points_along_its_direction():
    assert ErrorModel(bias_mm=2).bias_xy == (2, 0)
    assert ErrorModel(bias_mm=2, bias_direction_deg=90).bias_xy == pytest.approx((0, 2))
    assert ErrorModel(bias_mm=2, bias_direction_deg=225).bias_xy == pytest.approx((-math.sqrt(2), -math.sqrt(2)))
    assert ErrorModel(bias_direction_deg=45).bias_xy == (0, 0)


def test_a_range_is_scored_at_evenly_spread_sigmas():
    assert ErrorModel(sigma_mm=3).sigmas_mm == [3]
    assert ErrorModel(sigma_range_mm=(1, 6)).sigmas_mm == pytest.approx([1, 2, 3, 4, 5, 6])
    assert len(ErrorModel(sigma_range_mm=(0.5, 2)).sigmas_mm) == RANGE_SIGMAS
    assert ErrorModel(sigma_range_mm=(2, 2)).sigmas_mm == [2]


def test_at_sigma_keeps_the_bias_and_yaw_and_drops_the_range():
    model = ErrorModel(sigma_range_mm=(1, 4), sigma_deg=5, bias_mm=1, bias_direction_deg=30)

    point = model.at_sigma(2.5)

    assert (point.sigma_mm, point.sigma_range_mm, point.sigma_deg, point.bias_xy) == (2.5, None, 5, model.bias_xy)
    assert CURVE_SIGMAS_MM == (0.5, 1.0, 2.0, 3.0, 4.0, 5.0)


@pytest.mark.parametrize("bad", [{"sigma_range_mm": (3, 1)}, {"sigma_range_mm": (-1, 1)}, {"sigma_mm": -1}, {"bias_mm": -0.5}])
def test_rejects_an_impossible_error_model(bad):
    with pytest.raises(ValueError):
        ErrorModel(**bad)
