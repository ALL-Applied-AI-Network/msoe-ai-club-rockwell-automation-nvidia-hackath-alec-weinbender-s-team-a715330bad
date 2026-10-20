import pytest

from api import worker


@pytest.fixture
def calls(monkeypatch, config):
    """Runs the worker against the test config, recording what it was asked to do instead of doing it."""
    made = []
    monkeypatch.setattr(worker, "load_config", lambda: config)
    monkeypatch.setattr(
        worker, "run_job", lambda db, job_id, *, sim, cad, outputs_dir: made.append(("run", job_id, sim.backend, outputs_dir))
    )
    monkeypatch.setattr(worker.test_plans, "predict_test_plan", lambda db, plan_id, *, sim: made.append(("predict", plan_id, sim.backend)))
    return made


def test_a_job_id_runs_the_job(calls, config):
    worker.main(["abc123"])

    assert calls == [("run", "abc123", "mock", config.outputs_dir)]


def test_predict_runs_a_test_plans_prediction(calls):
    worker.main(["abc123", "predict", "7"])

    assert calls == [("predict", 7, "mock")]


@pytest.mark.parametrize("args", [[], ["abc123", "predict"], ["abc123", "predict", "x"], ["abc123", "other", "7"]])
def test_anything_else_prints_the_usage(calls, args):
    with pytest.raises(SystemExit, match="usage"):
        worker.main(args)
    assert calls == []
