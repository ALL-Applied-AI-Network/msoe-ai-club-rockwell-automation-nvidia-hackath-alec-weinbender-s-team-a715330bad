import json

FORM = {
    "task": "pick caps",
    "shape": "cylinder",
    "diameter_mm": "12",
    "length_mm": "20",
    "upright": "true",
    "budget": "5",
    "batch_size": "4",
}


def test_create_job_from_the_form_starts_a_worker(client, spawned):
    response = client.post("/api/jobs", data=FORM)

    assert response.status_code == 200
    job_id = response.json()["id"]
    assert spawned == [job_id]
    listed = client.get("/api/jobs").json()
    assert [(j["id"], j["status"], j["progress"], j["part"]["diameter_mm"]) for j in listed] == [(job_id, "queued", 0, 12)]


def test_blank_optional_fields_fall_back_to_defaults(client):
    job_id = client.post("/api/jobs", data={**FORM, "batch_size": "", "seed": ""}).json()["id"]

    config = client.get(f"/api/jobs/{job_id}").json()["config"]

    assert (config["batch_size"], config["seed"]) == (16, 0)


def test_part_file_is_stored_under_its_name(client):
    job_id = client.post("/api/jobs", data=FORM, files={"part_file": ("cap.stl", b"solid cap")}).json()["id"]

    assert client.get(f"/api/jobs/{job_id}").json()["part_name"] == "cap.stl"


def test_missing_task_is_a_validation_error(client):
    assert client.post("/api/jobs", data={"budget": "5"}).status_code == 422


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/scad").status_code == 404
    assert client.get("/api/jobs/nope/finger").status_code == 404


def test_only_stopped_jobs_can_be_resumed(client):
    job_id = client.post("/api/jobs", data=FORM).json()["id"]

    response = client.post(f"/api/jobs/{job_id}/resume")

    assert (response.status_code, response.json()) == (409, {"detail": "not resumable"})


def test_review_rules_come_back_as_readable_422s(client):
    job_id = client.post("/api/jobs", data=FORM).json()["id"]

    bad = client.post(f"/api/jobs/{job_id}/review", data={"status": "bogus"})
    unnamed = client.post(f"/api/jobs/{job_id}/review", data={"status": "approved"})
    ok = client.post(f"/api/jobs/{job_id}/review", data={"status": "approved", "reviewer": "alec"})

    assert (bad.status_code, bad.json()) == (422, {"detail": "bad status"})
    assert (unnamed.status_code, unnamed.json()) == (422, {"detail": "reviewer name required"})
    assert ok.json() == {"ok": True}
    assert client.get(f"/api/jobs/{job_id}").json()["review"]["reviewer"] == "alec"


def test_physical_trial_accepts_blank_measurements(client):
    job_id = client.post("/api/jobs", data=FORM).json()["id"]

    client.post(f"/api/jobs/{job_id}/physical", data={"success": "1", "placement_error_mm": "", "cycle_time_s": "4.2"})

    [trial] = client.get(f"/api/jobs/{job_id}").json()["physical"]
    assert (trial["success"], trial["placement_error_mm"], trial["cycle_time_s"], trial["finger"]) == (1, None, 4.2, "optimized")


def test_finished_job_detail_has_everything_the_ui_reads(finished_client, finished_job):
    detail = finished_client.get(f"/api/jobs/{finished_job.job_id}").json()

    assert detail["status"] == "done" and detail["progress"] == 1
    assert {"trials", "result", "meta", "review", "physical"} <= detail.keys()
    assert {"round", "kind", "params", "success_rate", "capture_radius_mm", "held"} <= detail["trials"][0].keys()
    assert {"predicted_success", "capture_radius_mm", "comparison", "grasp_pose", "kind", "params"} <= detail["result"].keys()
    assert {"runtime_s", "n_trials", "n_rounds", "grid", "gpu", "sim_backend"} <= detail["meta"].keys()


def test_events_stream_reports_progress_and_ends_when_finished(finished_client, finished_job):
    response = finished_client.get(f"/api/jobs/{finished_job.job_id}/events")

    [event] = [json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line]
    assert response.headers["content-type"].startswith("text/event-stream")
    assert set(event) == {"status", "stage", "n_done", "n_total", "best_value"}
    assert event["status"] == "done"


def test_cad_download_is_named_after_the_job(finished_client, finished_job):
    response = finished_client.get(f"/api/jobs/{finished_job.job_id}/scad")

    assert response.status_code == 200
    assert f'filename="fingers_{finished_job.job_id}.scad"' in response.headers["content-disposition"]


def test_finger_geometry_is_served_for_the_preview(finished_client, finished_job):
    body = finished_client.get(f"/api/jobs/{finished_job.job_id}/finger").json()

    assert body["jaw_open_mm"] == 6 and len(body["extent_mm"]) == 3
    piece = body["finger"]["pieces"][0]
    assert len(piece["points"][0]) == 3 and len(piece["triangles"][0]) == 3
