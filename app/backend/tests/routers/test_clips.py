"""routers/clips.py: the clip calls over a copy of the finished experiment marked as run on the Isaac sim."""

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_config, get_db
from api.main import app
from api.services import clips


@pytest.fixture
def isaac_client(isaac_job, spawned):
    app.dependency_overrides = {get_config: lambda: isaac_job.config, get_db: lambda: isaac_job.db}
    yield TestClient(app), isaac_job
    app.dependency_overrides = {}


def test_a_clip_is_asked_for_listed_and_played_once_recorded(isaac_client, spawned, filming_sim):
    client, job = isaac_client
    response = client.post(f"/api/jobs/{job.job_id}/clips", json={"design": "d1", "offset": {"dx": 2.0, "dy": -1.0}})

    assert response.status_code == 202, response.text
    clip = response.json()
    assert {key: clip[key] for key in ("design", "status", "views", "outcome", "result", "matches_result")} == {
        "design": "D1",
        "status": "queued",
        "views": ["closeup", "side"],
        "outcome": None,
        "result": None,
        "matches_result": None,
    }
    assert clip["offset"] == {"dx": 2.0, "dy": -1.0, "yaw_deg": 0.0}
    assert spawned == [(job.job_id, "clip", str(clip["id"]))]
    assert client.get(f"/api/jobs/{job.job_id}/clips/{clip['id']}.mp4").status_code == 409  # not recorded yet

    clips.record_clip(job.db, clip["id"], sim=filming_sim(), outputs_dir=job.config.outputs_dir)

    [listed] = client.get(f"/api/jobs/{job.job_id}/clips").json()
    assert (listed["status"], listed["outcome"], listed["duration_s"]) == ("ready", "held", 4.9)
    video = client.get(f"/api/jobs/{job.job_id}/clips/{clip['id']}.mp4", params={"view": "side"})
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4" and video.content == b"side mp4"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"design": "D9", "offset": {"dx": 0, "dy": 0}}, 404),
        ({"design": "D1", "offset": {"dx": 80, "dy": 0}}, 422),
        ({"design": "", "offset": {"dx": 0, "dy": 0}}, 422),
        ({"design": "D1"}, 422),
    ],
    ids=["unknown design", "offset out of range", "no design", "no offset"],
)
def test_bad_clip_requests(isaac_client, body, status):
    client, job = isaac_client
    assert client.post(f"/api/jobs/{job.job_id}/clips", json=body).status_code == status


def test_a_mock_experiment_answers_409_with_why(finished_client, finished_job):
    response = finished_client.post(f"/api/jobs/{finished_job.job_id}/clips", json={"design": "D1", "offset": {"dx": 0, "dy": 0}})
    assert response.status_code == 409 and "mock sim" in response.json()["detail"]


def test_unknown_jobs_and_clips_are_404(isaac_client):
    client, job = isaac_client
    assert client.get("/api/jobs/nope/clips").status_code == 404
    assert client.get(f"/api/jobs/{job.job_id}/clips/99.mp4").status_code == 404
