"""scripts/demo_data.py: one experiment through the same helpers the full seed uses (the whole seed takes minutes), with
its made-up physical trials labelled as such, and the guard that keeps demo data out of an existing database."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from api.services import jobs, physical_trials

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_data.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo_data", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_demo_experiment_runs_and_its_physical_trials_say_they_are_made_up(demo, db, config, cad, profile_id, spawned):
    part_id = demo._part(db, config, cad, "vial-cap")
    demo._material(db, part_id, "pla", "standing on an end")
    job = jobs.create_job(db, config, demo._spec(db, "Vial cap", part_id, profile_id, budget=4), start=False)
    demo.optimizer.run_job(db, job.id, sim=demo.MockSim(), cad=cad, outputs_dir=config.outputs_dir)

    demo._tracker(db, config, job.id, logged=0.5, approved=False)

    done = jobs.get_job(db, job.id)
    assert done.status == "done" and done.name.startswith(demo.PREFIX) and done.sim_backend == "mock"
    trials = physical_trials.list_trials(db, job.id)
    assert trials, "half the planned trials are logged"
    assert all(t.operator == demo.OPERATOR and t.notes == demo.NOTE for t in trials)
    assert physical_trials.physical_badge(db, job.id) == "in_progress"
    assert not spawned, "the demo runs everything in-process: no worker is started"


def test_made_up_outcomes_mostly_agree_with_the_sim_and_are_repeatable(demo):
    first, again, rng = np.random.default_rng(1), np.random.default_rng(1), np.random.default_rng(2)

    assert [demo._made_up_held(True, 1.0, 0.0, first) for _ in range(20)] == [demo._made_up_held(True, 1.0, 0.0, again) for _ in range(20)]
    agree = sum(demo._made_up_held(True, 1.0, 0.0, rng) for _ in range(200))

    assert agree > 150


def test_it_fills_an_empty_database_but_never_one_with_data(demo, db, config, cad, monkeypatch):
    seeded = []
    monkeypatch.setattr(demo, "seed", lambda config, live=False: seeded.append(config.data_dir) or [])
    demo.main(["--data-dir", str(config.data_dir)])  # migrated but empty, as the API leaves it on a first start
    assert seeded == [config.data_dir.resolve()]

    demo._part(db, config, cad, "cube-10mm")
    with pytest.raises(SystemExit, match="--reset"):
        demo.main(["--data-dir", str(config.data_dir)])
