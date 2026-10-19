from pathlib import Path

from api.clients.cad import OpenScadCad
from api.clients.llm import MockLlm
from api.clients.sim import MockSim
from api.models.job import JobConfig
from api.models.part import Part
from api.services import jobs
from api.services.optimizer import camera_offset, run_job, wilson


class BrokenLlm:
    backend = "broken"

    def suggest(self, part, task, k):
        raise RuntimeError("LLM is down")

    def close(self):
        pass


def test_wilson_interval_contains_the_rate_and_stays_in_0_1():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(7, 10)
    assert 0 <= lo < 0.7 < hi <= 1
    assert wilson(10, 10)[1] == 1


def test_camera_offsets_are_the_same_for_every_design():
    assert [camera_offset(i, 3, 8, seed=1) for i in range(5)] == [camera_offset(i, 3, 8, seed=1) for i in range(5)]
    assert camera_offset(0, 3, 8, seed=1) != camera_offset(0, 3, 8, seed=2)


def test_a_finished_job_has_trials_a_result_and_a_cad_file(finished_job):
    db, job_id = finished_job.db, finished_job.job_id
    detail = jobs.get_job_detail(db, job_id)

    assert detail.job.status == "done"
    assert 0 < len(detail.trials) <= detail.job.config.budget
    assert detail.result is not None
    assert 0 <= detail.result.ci_low <= detail.result.predicted_success <= detail.result.ci_high <= 1
    assert Path(detail.result.scad_path).read_text().startswith(f"// {detail.result.template} finger")
    assert detail.meta["sim_backend"] == "mock"
    assert any(s.trial_number is not None for s in detail.suggestions), "LLM suggestions are evaluated first"


def test_a_failure_is_stored_on_the_job_not_raised(db, config, spawned, tmp_path):
    job_id = jobs.create_job(db, config, task="pick", part=Part(), job_config=JobConfig(budget=2))

    run_job(db, job_id, llm=BrokenLlm(), sim=MockSim(), cad=OpenScadCad(), outputs_dir=tmp_path)

    job = jobs.get_job(db, job_id)
    assert job.status == "failed"
    assert "LLM is down" in job.error


def test_resuming_replays_the_checkpoint_without_redoing_the_llm_step(db, config, spawned, tmp_path):
    job_id = jobs.create_job(db, config, task="pick", part=Part(), job_config=JobConfig(budget=3, n_grasps=10, n_suggestions=2, workers=1))
    run_job(db, job_id, llm=MockLlm(), sim=MockSim(), cad=OpenScadCad(), outputs_dir=tmp_path)
    before = jobs.get_job_detail(db, job_id)
    jobs.update_job(db, job_id, status="interrupted")

    run_job(db, job_id, llm=BrokenLlm(), sim=MockSim(), cad=OpenScadCad(), outputs_dir=tmp_path)

    after = jobs.get_job_detail(db, job_id)
    assert after.job.status == "done"
    assert [t.number for t in after.trials] == [t.number for t in before.trials]
    assert len(after.suggestions) == len(before.suggestions)
