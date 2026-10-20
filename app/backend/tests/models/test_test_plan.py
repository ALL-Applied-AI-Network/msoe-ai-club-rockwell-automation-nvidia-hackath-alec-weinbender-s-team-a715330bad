import numpy as np
import pytest

from api.models.error_model import ErrorModel
from api.models.test_plan import offset_key, pointwise_offsets, random_offsets, trial_id, trial_number


def test_25_pointwise_offsets_centre_axes_and_diagonals():
    offsets = pointwise_offsets()

    assert len(offsets) == len(set(offsets)) == 25
    assert offsets[0] == (0.0, 0.0)
    for d in (1, 2, 3, 4, 6):
        assert {(d, 0), (-d, 0), (0, d), (0, -d)} <= set(offsets)
    assert {(3, 3), (-3, 3), (-3, -3), (3, -3)} <= set(offsets)


def test_random_offsets_are_seeded_and_follow_the_error_model():
    error = ErrorModel(sigma_mm=2.0, sigma_deg=5.0, bias_mm=1.0, bias_direction_deg=90)

    first = random_offsets(error, 2000, np.random.default_rng(7), yaw=True)
    again = random_offsets(error, 2000, np.random.default_rng(7), yaw=True)
    other = random_offsets(error, 2000, np.random.default_rng(8), yaw=True)

    assert first == again and first != other
    x, y, yaw = np.array(first).T
    assert (x.mean(), y.mean(), yaw.mean()) == pytest.approx((0.0, 1.0, 0.0), abs=0.15)  # the bias points along +y
    assert (x.std(), y.std(), yaw.std()) == pytest.approx((2.0, 2.0, 5.0), rel=0.06)
    assert all(round(v, 2) == v for v in x[:50])  # stored as commanded: to 0.01


def test_a_part_round_from_above_draws_no_yaw():
    offsets = random_offsets(ErrorModel(), 30, np.random.default_rng(1), yaw=False)

    assert [yaw for _, _, yaw in offsets] == [0.0] * 30


def test_trial_ids_round_trip_and_tolerate_typing():
    assert trial_id(7) == "T0007" and trial_id(12345) == "T12345"
    assert [trial_number(v) for v in ("T0007", "t7", " T 0007 ", "T12345")] == [7, 7, 7, 12345]
    assert [trial_number(v) for v in ("7", "X0007", "", "T")] == [None] * 4


def test_offset_keys_compare_equal_across_rounding_and_signed_zero():
    assert offset_key(1.0000000001, -0.0, 0) == offset_key(1, 0.0, 0.0) == (1.0, 0.0, 0.0)
