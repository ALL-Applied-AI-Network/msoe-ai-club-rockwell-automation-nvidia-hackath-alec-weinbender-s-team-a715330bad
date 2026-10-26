"""Evaluation jobs through /api/jobs (the routes they share with generation jobs, and their own), and adding a generation
job's design to the finger library."""

import pytest


def evaluation(e, **changes) -> dict:
    return {"kind": "evaluation", "part_id": e.part_id, "cell_profile_id": e.profile_id} | changes


def test_an_evaluation_plans_and_starts_like_any_job(evaluated_copy_client, evaluated_copy, spawned):
    e = evaluated_copy

    plan = evaluated_copy_client.post("/api/jobs/plan", json=evaluation(e))
    created = evaluated_copy_client.post("/api/jobs", json=evaluation(e, name="Cube vs the library"))

    assert plan.status_code == 200 and plan.json()["kind"] == "evaluation" and plan.json()["failed_step"] is None
    assert len(plan.json()["fingers"]) == 3 and plan.json()["totals"]["simulated"] > 0
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "evaluation" and body["name"] == "Cube vs the library"
    assert spawned == [(body["id"],)]
    detail = evaluated_copy_client.get(f"/api/jobs/{body['id']}").json()
    assert detail["kind"] == "evaluation" and detail["spec"]["kind"] == "evaluation" and detail["plan"]["kind"] == "evaluation"
    assert detail["card"]["kind"] == "evaluation" and detail["card"]["status"] == "queued"


def test_a_spec_without_a_kind_is_still_a_generation_job(evaluated_copy_client, evaluated_copy):
    e = evaluated_copy
    spec = {"part_id": e.part_id, "cell_profile_id": e.profile_id, "grasp": {"angle_deg": 0}, "budget": 8}

    plan = evaluated_copy_client.post("/api/jobs/plan", json=spec)

    assert plan.status_code == 200 and plan.json()["kind"] == "generation" and plan.json()["searches"]


def test_a_blocked_evaluation_is_422_with_its_steps(evaluated_copy_client, evaluated_copy):
    response = evaluated_copy_client.post("/api/jobs", json=evaluation(evaluated_copy, finger_ids=["nope"]))

    assert response.status_code == 422 and response.json()["detail"]["failed_step"] == 3


def test_the_ranking_and_its_rescore(evaluated_client, evaluated):
    own = evaluated_client.get(f"/api/jobs/{evaluated.job_id}/ranking")
    tight = evaluated_client.post(f"/api/jobs/{evaluated.job_id}/ranking/rescore", json={"error": {"preset": "custom", "sigma_mm": 0.5}})

    assert own.status_code == 200 and tight.status_code == 200
    assert [f["rank"] for f in own.json()["fingers"]] == [1, 2, 3] and not own.json()["rescored"]
    assert tight.json()["rescored"] and tight.json()["error"]["sigma_mm"] == 0.5
    best = own.json()["fingers"][0]["best"][0]
    assert {"pose_key", "grasp_key", "angle_deg", "tip_height_mm", "jaw_close_mm", "success", "stage"} <= set(best)


def test_each_kind_is_409_at_the_others_results(evaluated_client, evaluated):
    ranking = evaluated_client.get(f"/api/jobs/{evaluated.generation_job_id}/ranking")
    results = evaluated_client.get(f"/api/jobs/{evaluated.job_id}/results")

    assert ranking.status_code == 409 and "generation job" in ranking.json()["detail"]
    assert results.status_code == 409 and "evaluation job" in results.json()["detail"]


def test_generate_spec_comes_back_ready_for_the_wizard(evaluated_client, evaluated):
    response = evaluated_client.post(f"/api/jobs/{evaluated.job_id}/generate-spec", params={"finger_id": evaluated.uploaded_id})
    unknown = evaluated_client.post(f"/api/jobs/{evaluated.job_id}/generate-spec", params={"finger_id": "nope"})

    assert response.status_code == 200
    spec = response.json()
    assert spec["kind"] == "generation" and spec["part_id"] == evaluated.part_id and len(spec["poses"]) == 1
    assert unknown.status_code == 404


def test_the_job_list_filters_by_kind(evaluated_client):
    kinds = {c["kind"] for c in evaluated_client.get("/api/jobs").json()}
    evaluations = evaluated_client.get("/api/jobs", params={"kind": "evaluation"}).json()

    assert kinds == {"generation", "evaluation"}
    assert [c["kind"] for c in evaluations] == ["evaluation"] and evaluations[0]["winner"]["label"].startswith("FNG-")


def test_a_batch_makes_one_evaluation_per_part(evaluated_copy_client, evaluated_copy, spawned, shapes, step_file):
    e = evaluated_copy
    bar = evaluated_copy_client.post("/api/parts", files={"part_file": ("bar.step", step_file(shapes["bar"], "bar.step"))}).json()
    evaluated_copy_client.patch(f"/api/parts/{bar['id']}", json={"material": "pla"})

    response = evaluated_copy_client.post("/api/jobs/batch", json=evaluation(e, part_ids=[e.part_id, bar["id"]]))

    assert response.status_code == 201, response.text
    made = response.json()
    assert len(made) == 2 and made[0]["batch_id"] == made[1]["batch_id"] is not None
    assert len(spawned) == 2


def test_a_design_joins_the_library_once(evaluated_copy_client, evaluated_copy):
    e = evaluated_copy

    added = evaluated_copy_client.post(f"/api/jobs/{e.generation_job_id}/designs/IMP/library", json={"name": "Cube imprint"})
    again = evaluated_copy_client.post(f"/api/jobs/{e.generation_job_id}/designs/IMP/library")
    stock = evaluated_copy_client.post(f"/api/jobs/{e.generation_job_id}/designs/STOCK/library")
    missing = evaluated_copy_client.post(f"/api/jobs/{e.generation_job_id}/designs/D9/library")

    assert added.status_code == 201 and added.json()["name"] == "Cube imprint" and added.json()["code"].startswith("FNG-")
    assert again.status_code == 409 and stock.status_code == 409 and missing.status_code == 404


@pytest.mark.parametrize("path", ["ranking", "results"])
def test_an_unknown_job_is_404(evaluated_client, path):
    assert evaluated_client.get(f"/api/jobs/nope/{path}").status_code == 404
