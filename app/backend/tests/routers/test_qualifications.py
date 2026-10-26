def test_logging_a_session_validates_the_pair(evaluated_copy_client, evaluated_copy):
    e = evaluated_copy
    (pair,) = evaluated_copy_client.get("/api/qualifications", params={"finger_id": e.generated_id, "part_id": e.part_id}).json()
    assert pair["status"] == "simulated" and pair["prediction"]["job_id"] == e.job_id

    logged = evaluated_copy_client.post(f"/api/qualifications/{pair['id']}/sessions", json={"trials": 10, "successes": 8})

    assert logged.status_code == 201
    body = logged.json()
    assert body["status"] == "validated" and body["measured_success"] == 0.8 and len(body["comparisons"]) == 1
    session_id = body["sessions"][0]["id"]
    patched = evaluated_copy_client.patch(f"/api/qualifications/{pair['id']}/sessions/{session_id}", json={"successes": 10})
    assert patched.json()["measured_success"] == 1.0
    removed = evaluated_copy_client.delete(f"/api/qualifications/{pair['id']}/sessions/{session_id}")
    assert removed.json()["status"] == "simulated"


def test_bad_sessions_and_unknown_pairs(evaluated_copy_client, evaluated_copy):
    e = evaluated_copy
    (pair,) = evaluated_copy_client.get("/api/qualifications", params={"finger_id": e.uploaded_id}).json()

    too_many = evaluated_copy_client.post(f"/api/qualifications/{pair['id']}/sessions", json={"trials": 2, "successes": 3})
    missing = evaluated_copy_client.post("/api/qualifications/999/sessions", json={"trials": 2, "successes": 1})
    no_part = evaluated_copy_client.post("/api/qualifications", json={"finger_id": e.uploaded_id, "part_id": "nope"})
    existing = evaluated_copy_client.post("/api/qualifications", json={"finger_id": e.uploaded_id, "part_id": e.part_id})

    assert too_many.status_code == 422 and missing.status_code == 404 and no_part.status_code == 422
    assert existing.status_code == 201 and existing.json()["id"] == pair["id"]
