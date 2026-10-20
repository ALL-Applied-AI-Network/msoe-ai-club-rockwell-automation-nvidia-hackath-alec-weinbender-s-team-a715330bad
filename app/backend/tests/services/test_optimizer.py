from pathlib import Path

import pytest

from api.clients.cad import OpenScadCad
from api.clients.sim import MockSim
from api.models.job import JobConfig
from api.models.part import Part
from api.models.search_space import SearchSpace
from api.services import jobs
from api.services.optimizer import BASELINES, _propose, _stale_rounds, run_job


class BrokenSim:
    backend = "broken"
    url = None

    def run_batch(self, part, fingers, offsets):
        raise RuntimeError("sim server is down")

    def close(self):
        pass


class CountingSim(MockSim):
    """The mock, counting the designs it's asked to simulate."""

    def __init__(self):
        self.designs = 0

    def run_batch(self, part, fingers, offsets):
        self.designs += len(fingers)
        return super().run_batch(part, fingers, offsets)


def test_a_finished_job_has_rounds_baselines_a_result_and_a_cad_file(finished_job):
    detail = jobs.get_job_detail(finished_job.db, finished_job.job_id)
    config = detail.job.config

    assert detail.job.status == "done"
    assert [t.kind for t in detail.trials if t.round == 0][: len(BASELINES)] == list(BASELINES)
    assert sum(t.kind == "search" for t in detail.trials) == config.budget
    assert {t.round for t in detail.trials} == {0, 1}
    assert all(len(t.held) == t.n_grasps == detail.trials[0].n_grasps for t in detail.trials)
    result = detail.result
    assert 0 <= result.predicted_success <= 1
    assert [c["name"] for c in result.comparison][:3] == ["optimized", "stock", "imprint"]
    assert result.comparison[0]["curve"]["0.5"] >= result.comparison[0]["curve"]["5"]
    assert Path(result.scad_path).read_text().startswith(f"// job {finished_job.job_id}")
    assert detail.meta["sim_backend"] == "mock" and detail.meta["n_rounds"] == 2


def test_a_failure_is_stored_on_the_job_not_raised(db, config, spawned, tmp_path):
    job_id = jobs.create_job(db, config, task="pick", part=Part(), job_config=JobConfig(budget=2, batch_size=2))

    run_job(db, job_id, sim=BrokenSim(), cad=OpenScadCad(), outputs_dir=tmp_path)

    job = jobs.get_job(db, job_id)
    assert job.status == "failed"
    assert "sim server is down" in job.error


def test_resuming_continues_after_the_last_checkpointed_round(db, config, spawned, tmp_path):
    job_id = jobs.create_job(db, config, task="pick", part=Part(shape="box"), job_config=JobConfig(budget=4, batch_size=2))
    run_job(db, job_id, sim=MockSim(), cad=OpenScadCad(), outputs_dir=tmp_path)
    before = jobs.get_job_detail(db, job_id)
    jobs.update_job(db, job_id, status="interrupted")
    sim = CountingSim()

    run_job(db, job_id, sim=sim, cad=OpenScadCad(), outputs_dir=tmp_path)

    after = jobs.get_job_detail(db, job_id)
    assert after.job.status == "done"
    assert [t.number for t in after.trials] == [t.number for t in before.trials]
    assert sim.designs == 3 + len(BASELINES), "only the finalists and baselines are re-validated; no round is redone"


def test_a_cancel_request_stops_the_job_between_rounds(db, config, spawned, tmp_path):
    job_id = jobs.create_job(db, config, task="pick", part=Part(), job_config=JobConfig(budget=4, batch_size=2))

    class CancelAfterOneRound(MockSim):  # the user presses Cancel while round 0 is simulating
        def run_batch(self, part, fingers, offsets):
            jobs.cancel_job(db, job_id)
            return super().run_batch(part, fingers, offsets)

    run_job(db, job_id, sim=CancelAfterOneRound(), cad=OpenScadCad(), outputs_dir=tmp_path)

    detail = jobs.get_job_detail(db, job_id)
    assert detail.job.status == "cancelled"
    assert {t.round for t in detail.trials} == {0}


@pytest.mark.parametrize("n_searched", [0, 6])
def test_proposals_are_points_of_the_unit_cube(finished_job, n_searched):
    detail = jobs.get_job_detail(finished_job.db, finished_job.job_id)
    space = SearchSpace(detail.job.part)
    searched = [t for t in detail.trials if t.kind == "search"][:n_searched]

    points = _propose(space, searched, q=4, seed=1)

    assert len(points) == 4
    assert all(len(p) == len(space.names) and all(0 <= v <= 1 for v in p) for p in points)


def test_stale_rounds_count_rounds_since_the_best_score_improved():
    class T:
        def __init__(self, round, rate, kind="search"):
            self.round, self.success_rate, self.kind = round, rate, kind

    assert _stale_rounds([]) == 0
    assert _stale_rounds([T(0, 0.9, "stock"), T(0, 0.5), T(1, 0.6), T(2, 0.6), T(3, 0.601)]) == 2
