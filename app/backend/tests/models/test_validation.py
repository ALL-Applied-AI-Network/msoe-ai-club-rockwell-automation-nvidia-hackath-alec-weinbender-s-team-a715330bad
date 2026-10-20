import pytest

from api.models.validation import wilson_interval


def test_the_wilson_interval_matches_published_values():
    # as scipy.stats.binomtest(k, n).proportion_ci(method="wilson") gives them
    assert wilson_interval(8, 10) == pytest.approx((0.4902, 0.9433), abs=1e-4)
    assert wilson_interval(0, 10) == pytest.approx((0.0, 0.2775), abs=1e-4)
    assert wilson_interval(10, 10) == pytest.approx((0.7225, 1.0), abs=1e-4)


def test_the_wilson_interval_stays_inside_zero_to_one_and_narrows_with_more_trials():
    small, large = wilson_interval(1, 2), wilson_interval(50, 100)

    assert 0 < small[0] < 0.5 < small[1] < 1
    assert large[1] - large[0] < small[1] - small[0]


def test_the_wilson_interval_needs_a_trial():
    with pytest.raises(ValueError):
        wilson_interval(0, 0)
