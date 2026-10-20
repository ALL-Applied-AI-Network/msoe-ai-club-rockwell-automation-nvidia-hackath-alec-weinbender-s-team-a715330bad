import json


def test_trials_jsonl_is_one_trial_per_line(finished_client, finished_job):
    response = finished_client.get("/api/export/trials.jsonl", params={"job_id": finished_job.job_id})

    assert response.status_code == 200 and response.headers["content-type"] == "application/x-ndjson"
    assert response.headers["content-disposition"] == f'attachment; filename="trials_{finished_job.job_id}.jsonl"'
    rows = [json.loads(line) for line in response.text.splitlines()]
    assert len(rows) == 25 and all(row["job_id"] == finished_job.job_id for row in rows)
    assert sum(row["chosen_best"] for row in rows) == 1


def test_every_jobs_trials_and_an_unknown_job(finished_client):
    assert finished_client.get("/api/export/trials.jsonl").status_code == 200
    assert finished_client.get("/api/export/trials.jsonl", params={"job_id": "nope"}).status_code == 404
