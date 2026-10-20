"""services/clips.py: asking for a clip, the worker filming it, and the videos it leaves, on a copy of the finished
experiment marked as run on the Isaac sim, with a fake sim that "films" by returning a few bytes per view."""

import os
import time

import pytest

from api.config import AppConfig, ComputeConfig, SimConfig
from api.models.clip import ClipOffset, ClipRequest
from api.services import clips, compute, jobs, results


def centre_of(job) -> ClipOffset:
    point = job.plan.final_grid.points()[0]
    return ClipOffset(dx=point["dx"], dy=point["dy"], yaw_deg=point["yaw_deg"])


def test_asking_for_a_clip_queues_it_and_starts_its_worker(isaac_job, spawned):
    clip = clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, ClipRequest(design="d1", offset=ClipOffset(dx=2, dy=0)))

    assert (clip.design, clip.status, clip.views, clip.outcome, clip.matches_result) == ("D1", "queued", ["closeup", "side"], None, None)
    assert clip.offset == ClipOffset(dx=2, dy=0, yaw_deg=0)
    assert spawned == [(isaac_job.job_id, "clip", str(clip.id))]


def test_the_same_design_and_offset_again_returns_its_clip_unless_it_failed(isaac_job, spawned, filming_sim):
    request = ClipRequest(design="STOCK", offset=ClipOffset(dx=1, dy=-1))
    first = clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, request)
    assert clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, request).id == first.id

    clips.record_clip(isaac_job.db, first.id, sim=filming_sim(fail="the GPU went away"), outputs_dir=isaac_job.config.outputs_dir)
    again = clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, request)

    assert again.id != first.id and len(spawned) == 2


def test_a_mock_experiment_cant_be_filmed(finished_job, spawned):
    with pytest.raises(clips.ClipsUnavailableError, match="mock sim"):
        clips.request_clip(
            finished_job.db, finished_job.config, finished_job.job_id, ClipRequest(design="D1", offset=ClipOffset(dx=0, dy=0))
        )
    assert spawned == []


def test_an_unknown_design_says_which_there_are(isaac_job, spawned):
    with pytest.raises(results.DesignNotFoundError, match="D1"):
        clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, ClipRequest(design="D9", offset=ClipOffset(dx=0, dy=0)))


def test_filming_needs_a_ready_gpu_when_the_app_manages_it(isaac_job, spawned):
    managed = AppConfig(
        data_dir=isaac_job.config.data_dir,
        sim=SimConfig(backend="http", url="http://127.0.0.1:9000"),
        compute=ComputeConfig(backends="gb10"),
    )

    with pytest.raises(compute.ComputeNotReadyError, match="isn't connected"):
        clips.request_clip(isaac_job.db, managed, isaac_job.job_id, ClipRequest(design="D1", offset=ClipOffset(dx=0, dy=0)))
    assert spawned == []


def test_the_worker_films_the_jobs_own_grasp_and_compares_it_with_the_result(isaac_job, spawned, filming_sim):
    db, config = isaac_job.db, isaac_job.config
    job = jobs.get_job(db, isaac_job.job_id)
    clip = clips.request_clip(db, config, job.id, ClipRequest(design="D1", offset=centre_of(job)))
    sim = filming_sim(held=False)

    clips.record_clip(db, clip.id, sim=sim, outputs_dir=config.outputs_dir)

    [(part, finger, offset, settings, views)] = sim.calls
    assert part == job.part and finger is not None and finger.pieces  # D1's own finger, on the job's part
    assert offset == centre_of(job).model_dump() and views == ["closeup", "side"]
    assert (settings.grip_force_n, settings.transport) == (job.plan.grip_force_n, job.spec.task.transport)
    done = clips.get_clip(db, job.id, clip.id)
    _, trial = results.final_trial(db, job.id, "D1")
    stored = "held" if trial.held[0] else "missed"
    assert (done.status, done.outcome, done.result, done.duration_s) == ("ready", "missed", stored, 4.9)
    assert done.matches_result == (stored == "missed") and done.recorded is not None
    assert clips.clip_video(db, config, job.id, clip.id, "side").read_bytes() == b"side mp4"


def test_stock_is_filmed_with_the_robots_own_fingers(isaac_job, spawned, filming_sim):
    off_grid = ClipOffset(dx=0.37, dy=0.11)
    clip = clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, ClipRequest(design="stock", offset=off_grid))
    sim = filming_sim()

    clips.record_clip(isaac_job.db, clip.id, sim=sim, outputs_dir=isaac_job.config.outputs_dir)

    assert sim.calls[0][1] is None
    done = clips.get_clip(isaac_job.db, isaac_job.job_id, clip.id)
    assert (done.outcome, done.result, done.matches_result) == ("held", None, None)  # no stored result off the grid


def test_a_failed_recording_is_stored_with_its_reason_and_has_no_video(isaac_job, spawned, filming_sim):
    db, config = isaac_job.db, isaac_job.config
    clip = clips.request_clip(db, config, isaac_job.job_id, ClipRequest(design="D1", offset=ClipOffset(dx=0, dy=0)))

    clips.record_clip(
        db, clip.id, sim=filming_sim(fail="can't reach the sim server at http://127.0.0.1:9000: refused"), outputs_dir=config.outputs_dir
    )

    failed = clips.get_clip(db, isaac_job.job_id, clip.id)
    assert failed.status == "failed" and "can't reach the sim server" in failed.error
    with pytest.raises(clips.ClipNotReadyError, match="failed"):
        clips.clip_video(db, config, isaac_job.job_id, clip.id, "closeup")


def test_clips_list_newest_first(isaac_job, spawned):
    for dx in (0, 1, 2):
        clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, ClipRequest(design="D1", offset=ClipOffset(dx=dx, dy=0)))

    assert [clip.offset.dx for clip in clips.list_clips(isaac_job.db, isaac_job.job_id)] == [2, 1, 0]


def test_a_clip_being_recorded_keeps_a_gpu_from_idling_out(isaac_job, spawned):
    clip = clips.request_clip(isaac_job.db, isaac_job.config, isaac_job.job_id, ClipRequest(design="D1", offset=ClipOffset(dx=0, dy=0)))
    assert not compute.active_work(isaac_job.db, time.time())

    clips._update(isaac_job.db, clip.id, status="recording", pid=os.getpid())

    assert compute.active_work(isaac_job.db, time.time())
