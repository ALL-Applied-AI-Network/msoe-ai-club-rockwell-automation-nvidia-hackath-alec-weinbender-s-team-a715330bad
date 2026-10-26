import pytest

from api.models.error_model import ErrorModel
from api.models.qualification import Prediction, RealSession, compare
from api.models.task import Task


def prediction(success: float) -> Prediction:
    return Prediction(
        job_id="j",
        experiment_id="EXP-0001",
        success=success,
        stage="final",
        n_grasps=963,
        error=ErrorModel(),
        task=Task(),
        grasps=[],
        sim_backend="isaac",
        created=0.0,
    )


def session(i: int, trials: int, successes: int, **values) -> RealSession:
    return RealSession(id=i, qualification_id=1, trials=trials, successes=successes, created=0.0, **values)


def test_natural_sessions_are_pooled_against_the_prediction():
    (pooled,) = compare(prediction(0.7), [session(1, 10, 7), session(2, 10, 8)])

    assert pooled.kind == "natural" and pooled.session_ids == [1, 2]
    assert (pooled.trials, pooled.successes, pooled.measured_success) == (20, 15, 0.75)
    assert pooled.wilson_low < 0.7 < pooled.wilson_high and not pooled.gap_flagged


def test_a_prediction_outside_the_interval_is_flagged():
    (pooled,) = compare(prediction(0.95), [session(1, 20, 8)])

    assert pooled.gap_flagged


def test_each_commanded_session_is_compared_with_its_own_prediction():
    found = compare(prediction(0.9), [session(1, 10, 5, kind="commanded", predicted_success=0.5), session(2, 10, 9, kind="commanded")])

    assert [c.kind for c in found] == ["commanded", "commanded"]
    assert found[0].predicted_success == 0.5 and not found[0].gap_flagged
    assert found[1].predicted_success is None and not found[1].gap_flagged, "nothing to compare with"


def test_nothing_to_compare_without_a_prediction():
    (pooled,) = compare(None, [session(1, 4, 4)])

    assert pooled.predicted_success is None and not pooled.gap_flagged and pooled.measured_success == 1.0


def test_a_session_cant_have_more_successes_than_trials():
    with pytest.raises(ValueError, match="more successes than trials"):
        session(1, 3, 4)
