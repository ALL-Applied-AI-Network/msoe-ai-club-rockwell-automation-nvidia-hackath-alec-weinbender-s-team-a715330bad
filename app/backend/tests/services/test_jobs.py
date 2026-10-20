import os

import pytest

from api.models.job import JobConfig
from api.models.part import Part
from api.services import jobs


@pytest.fixture
def job_id(db, config, spawned) -> str:
    return jobs.create_job(db, config, task="pick", part=Part(diameter_mm=12), job_config=JobConfig(budget=5))


def test_create_job_stores_it_queued_and_starts_a_worker(db, job_id, spawned):
    job = jobs.get_job(db, job_id)

    assert job.status == "queued"
    assert job.part == Part(diameter_mm=12)
    assert job.config == JobConfig(budget=5)
    assert job.n_total == 5
    assert spawned == [job_id]


def test_create_job_keeps_only_the_uploaded_file_name(db, config, spawned):
    upload = ("..\\..\\outside/cup.stl", b"solid cup")

    job = jobs.get_job(db, jobs.create_job(db, config, task="pick", part=Part(), job_config=JobConfig(), upload=upload))

    assert job.part_name == "cup.stl"
    assert (config.uploads_dir / f"{job.id}_cup.stl").read_bytes() == b"solid cup"


def test_unknown_job_raises(db):
    with pytest.raises(jobs.JobNotFoundError):
        jobs.get_job(db, "nope")
    with pytest.raises(jobs.JobNotFoundError):
        jobs.result_file(db, "nope")
    with pytest.raises(jobs.JobNotFoundError):
        jobs.result_finger(db, "nope")


def test_cancel_asks_the_worker_to_stop(db, job_id):
    jobs.cancel_job(db, job_id)

    assert jobs.get_job(db, job_id).cancel_requested == 1


@pytest.mark.parametrize("status", ["interrupted", "cancelled", "failed"])
def test_resume_restarts_stopped_jobs(db, config, job_id, spawned, status):
    jobs.update_job(db, job_id, status=status)

    jobs.resume_job(db, config, job_id)

    assert spawned == [job_id, job_id]


@pytest.mark.parametrize("status", ["queued", "running", "done"])
def test_resume_refuses_jobs_that_are_not_stopped(db, config, job_id, status):
    jobs.update_job(db, job_id, status=status)

    with pytest.raises(jobs.JobNotResumableError):
        jobs.resume_job(db, config, job_id)


def test_startup_marks_jobs_with_a_dead_worker_interrupted(db, config, spawned):
    dead = jobs.create_job(db, config, task="a", part=Part(), job_config=JobConfig())
    alive = jobs.create_job(db, config, task="b", part=Part(), job_config=JobConfig())
    jobs.update_job(db, dead, status="running", pid=None)
    jobs.update_job(db, alive, status="running", pid=os.getpid())

    jobs.mark_interrupted(db)

    assert jobs.get_job(db, dead).status == "interrupted"
    assert jobs.get_job(db, alive).status == "running"
