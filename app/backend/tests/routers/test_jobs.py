import json

import pytest

from api.clients.sim import MockSim
from api.db.tables import ComputeSessionRow
from api.services import cell_profiles, jobs, optimizer, parts

CUBE_LOCKS = {"pad_width_mm": 12.0, "slack_mm": 2.0, "tip_height_mm": 3.0, "lead_in_mm": 0.0}


@pytest.fixture
def cube_id(db, config, cad, shapes, step_file) -> str:
    """A 10 mm PLA cube standing on the table, ready for a job."""
    record = parts.create_part(db, config, cad, "cube.step", step_file(shapes["cube"], "cube.step"), None)
    return parts.update_part(db, record.id, {"material": "pla", "pose": 0}).id


def spec(part_id: str, profile_id: int, **changes) -> dict:
    return {"part_id": part_id, "cell_profile_id": profile_id, "grasp": {"angle_deg": 0}, "budget": 14} | changes


def test_with_a_managed_gpu_a_job_waits_for_a_ready_session(client, config, db, profile_id, cube_id, spawned, monkeypatch):
    """COMPUTE_BACKENDS=brev: a job (or a resume) needs a ready GPU session (services/compute.py)."""
    monkeypatch.setattr(config.compute, "backends", "brev")

    refused = client.post("/api/jobs", json=spec(cube_id, profile_id))

    assert refused.status_code == 409 and "choose a target in the GPU panel" in refused.json()["detail"]
    assert spawned == []
    with db.session() as s:
        s.add(ComputeSessionRow(backend="brev", instance="isaac-launchable", status="ready"))
    created = client.post("/api/jobs", json=spec(cube_id, profile_id))
    assert created.status_code == 201 and spawned == [(created.json()["id"],)]


def test_plan_is_200_with_blockers_and_the_first_step(client, profile_id, cube_id, db, config, cad, shapes, step_file):
    bare = parts.create_part(db, config, cad, "bare.step", step_file(shapes["cube"]), None)

    ready = client.post("/api/jobs/plan", json=spec(cube_id, profile_id))
    blocked = client.post("/api/jobs/plan", json=spec(bare.id, profile_id))

    assert ready.status_code == blocked.status_code == 200
    assert ready.json()["blockers"] == [] and ready.json()["failed_step"] is None and ready.json()["totals"]["search_designs"] == 16
    body = blocked.json()
    assert body["failed_step"] == 1 and [b["step"] for b in body["blockers"]] == [1, 2] and len(body["blocked"]) == 2


def test_create_starts_the_job_and_a_blocked_spec_is_422(client, profile_id, cube_id, spawned):
    created = client.post("/api/jobs", json=spec(cube_id, profile_id, name="cube test"))

    assert created.status_code == 201
    body = created.json()
    assert (body["experiment_id"], body["name"]) == ("EXP-0001", "cube test") and spawned == [(body["id"],)]
    refused = client.post("/api/jobs", json=spec(cube_id, 999))
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["failed_step"] == 4 and detail["blockers"][0]["step"] == 4 and "cell profile 999" in detail["reasons"][0]
    planned_family = client.post("/api/jobs", json=spec(cube_id, profile_id, families=[{"family": "imprint"}]))
    assert planned_family.status_code == 422 and "planned" in json.dumps(planned_family.json())
    copied = client.post("/api/jobs", json=spec(cube_id, profile_id, duplicated_from=body["id"]))
    assert copied.status_code == 201 and client.get(f"/api/jobs/{copied.json()['id']}").json()["duplicated_from"] == body["id"]
    assert client.post("/api/jobs", json=spec(cube_id, profile_id, duplicated_from="nope")).status_code == 422


def test_cards_list_and_filter(client, profile_id, cube_id, db):
    first = client.post("/api/jobs", json=spec(cube_id, profile_id)).json()["id"]
    second = client.post("/api/jobs", json=spec(cube_id, profile_id)).json()["id"]
    jobs.update_job(db, second, status="failed", failure="sim: unreachable", failed_step=None)

    cards = client.get("/api/jobs").json()

    assert [c["id"] for c in cards] == [second, first]
    card = cards[1]
    assert (card["experiment_id"], card["part_name"], card["task_kind"], card["sim_backend"], card["status"]) == (
        "EXP-0001",
        "cube.step",
        "drop",
        "mock",
        "queued",
    )
    assert (card["round"], card["n_rounds"], card["n_done"], card["n_total"], card["physical_badge"]) == (0, 4, 0, 21, "none")
    assert cards[0]["failure"] == "sim: unreachable"
    assert [c["id"] for c in client.get("/api/jobs", params={"status": "failed"}).json()] == [second]
    assert client.get("/api/jobs", params={"backend": "isaac"}).json() == []
    assert len(client.get("/api/jobs", params={"part_id": cube_id}).json()) == 2
    assert client.get("/api/jobs", params={"status": "bogus"}).status_code == 422


def test_get_rename_duplicate_cancel_and_resume(client, profile_id, cube_id, db):
    job_id = client.post("/api/jobs", json=spec(cube_id, profile_id)).json()["id"]

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["card"]["id"] == job_id and detail["plan"]["searches"][0]["key"] == "vpad" and detail["review"] is None
    assert client.get("/api/jobs/nope").status_code == 404
    renamed = client.patch(f"/api/jobs/{job_id}", json={"name": "renamed"})
    assert renamed.status_code == 200 and (renamed.json()["name"], renamed.json()["experiment_id"]) == ("renamed", "EXP-0001")
    assert client.patch(f"/api/jobs/{job_id}", json={"name": "   "}).status_code == 422
    copy = client.post(f"/api/jobs/{job_id}/duplicate").json()
    assert copy["name"] == "renamed (copy)" and copy["part_id"] == cube_id
    assert client.post(f"/api/jobs/{job_id}/cancel").json() == {"ok": True}
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    assert client.post(f"/api/jobs/{job_id}/resume").status_code == 409  # still queued
    jobs.update_job(db, job_id, status="interrupted")
    assert client.post(f"/api/jobs/{job_id}/resume").status_code == 200


def test_results_and_rescore(finished_client, finished_job):
    job_id = finished_job.job_id

    view = finished_client.get(f"/api/jobs/{job_id}/results")
    rescored = finished_client.post(f"/api/jobs/{job_id}/rescore", json={"task": {"kind": "place", "offset_tolerance_mm": 1.0}})

    assert view.status_code == rescored.status_code == 200
    assert view.json()["summary"]["best"]["label"] == "D1" and not view.json()["header"]["rescored"]
    assert rescored.json()["header"]["rescored"] and rescored.json()["summary"]["task_metric_label"] == "held grasps within 1 mm"
    sigma = finished_client.post(f"/api/jobs/{job_id}/rescore", json={"error": {"preset": "custom", "sigma_mm": 1.0, "sigma_deg": 3.0}})
    assert sigma.json()["curves"]["target_sigma_mm"] == 1.0
    assert finished_client.post(f"/api/jobs/{job_id}/rescore", json={"task": {"kind": "place"}}).status_code == 422  # no tolerance
    assert finished_client.get("/api/jobs/nope/results").status_code == 404


def test_events_stream_the_card_until_the_job_is_finished(finished_client, finished_job):
    with finished_client.stream("GET", f"/api/jobs/{finished_job.job_id}/events") as response:
        lines = [line for line in response.iter_lines() if line]

    assert response.headers["content-type"].startswith("text/event-stream")
    assert len(lines) == 1 and lines[0].startswith("data: ")
    card = json.loads(lines[0].removeprefix("data: "))
    assert card["status"] == "done" and card["winner"]["label"] == "D1" and card["stock"]["label"] == "STOCK"


def test_downloads_of_the_best_design(finished_client, finished_job):
    base = f"/api/jobs/{finished_job.job_id}/designs"
    name = jobs.get_job(finished_job.db, finished_job.job_id).name

    step = finished_client.get(f"{base}/D1/cad")
    stl = finished_client.get(f"{base}/D1/cad", params={"format": "stl", "side": "R"})
    sheet = finished_client.get(f"{base}/D1/print-sheet.pdf")
    checks = finished_client.get(f"{base}/D1/checks")

    assert step.status_code == stl.status_code == sheet.status_code == checks.status_code == 200
    assert step.content.startswith(b"ISO-10303-21") and f'filename="{name}_EXP-0001_D1_MOCK.step"' in step.headers["content-disposition"]
    assert stl.headers["content-type"] == "model/stl" and "_D1_MOCK_R.stl" in stl.headers["content-disposition"]
    assert sheet.content.startswith(b"%PDF") and sheet.headers["content-type"] == "application/pdf"
    assert checks.json()["blocked"] is False and {c["name"] for c in checks.json()["checks"]} >= {"solid", "finger length"}
    pose = finished_client.get(f"{base}/D1/grasp-pose").json()
    text = finished_client.get(f"{base}/D1/grasp-pose", params={"format": "text"})
    assert pose["grasp_angle_deg"] == 0 and text.headers["content-type"].startswith("text/plain") and "tip_height_mm: " in text.text
    assert finished_client.get(f"{base}/STOCK/cad").status_code == 422
    assert finished_client.get(f"{base}/D9/cad").status_code == 404
    assert finished_client.get(f"{base}/D1/cad", params={"format": "obj"}).status_code == 422


def test_the_finger_preview_and_run_metadata(finished_client, finished_job):
    job_id = finished_job.job_id

    finger = finished_client.get(f"/api/jobs/{job_id}/finger")
    stock = finished_client.get(f"/api/jobs/{job_id}/finger", params={"design": "STOCK"})
    meta = finished_client.get(f"/api/jobs/{job_id}/run-metadata.json")

    assert finger.status_code == stock.status_code == meta.status_code == 200
    body = finger.json()
    assert body["label"] == "D1" and body["jaw_open_mm"] == 6.0 and len(body["right"]) == len(body["finger"]["pieces"])
    assert stock.json()["label"] == "STOCK"
    assert meta.json()["experiment_id"] == "EXP-0001" and "attachment" in meta.headers["content-disposition"]


def test_a_job_without_its_final_test_has_nothing_to_download(client, profile_id, cube_id):
    job_id = client.post("/api/jobs", json=spec(cube_id, profile_id)).json()["id"]

    assert client.get(f"/api/jobs/{job_id}/results").json()["summary"] is None
    assert client.get(f"/api/jobs/{job_id}/designs/D1/cad").status_code == 409
    assert client.get(f"/api/jobs/{job_id}/finger").status_code == 409
    assert client.get(f"/api/jobs/{job_id}/run-metadata.json").status_code == 409


def test_a_blocked_export_is_409_with_the_failed_checks(client, db, config, cad, profile_id, cube_id):
    cell = cell_profiles.get_profile(db, profile_id).profile.model_copy(update={"max_finger_length_mm": 50.0})
    short = cell_profiles.create_profile(db, "short fingers", cell)
    job_id = client.post("/api/jobs", json=spec(cube_id, short.id, families=[{"locks": CUBE_LOCKS}])).json()["id"]
    optimizer.run_job(db, job_id, sim=MockSim(), cad=cad, outputs_dir=config.outputs_dir)

    response = client.get(f"/api/jobs/{job_id}/designs/D1/cad")

    assert response.status_code == 409
    failed = response.json()["detail"]["failed_checks"]
    assert [c["name"] for c in failed] == ["finger length"] and failed[0]["blocking"] and not failed[0]["ok"]
    assert client.get(f"/api/jobs/{job_id}/designs/D1/print-sheet.pdf").status_code == 409
    assert client.get(f"/api/jobs/{job_id}/designs/D1/checks").json()["blocked"] is True


def test_the_review_gate_needs_a_reviewer_to_approve(client, profile_id, cube_id):
    job_id = client.post("/api/jobs", json=spec(cube_id, profile_id)).json()["id"]

    assert client.post(f"/api/jobs/{job_id}/review", data={"status": "approved"}).status_code == 422
    assert client.post(f"/api/jobs/{job_id}/review", data={"status": "approved", "reviewer": "Ana"}).json() == {"ok": True}
    assert client.get(f"/api/jobs/{job_id}").json()["review"]["reviewer"] == "Ana"


def test_the_finger_preview_takes_a_resting_pose(two_pose_client, two_pose_job):
    url = f"/api/jobs/{two_pose_job.job_id}/finger"

    standing, unknown = two_pose_client.get(url, params={"pose": "p1"}), two_pose_client.get(url, params={"pose": "p9"})

    assert standing.status_code == 200 and (standing.json()["pose"], standing.json()["pose_label"]) == ("p1", "standing")
    assert unknown.status_code == 404
