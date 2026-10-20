import csv
import io
import json

import pytest

from api.clients.sim import MockSim
from api.db.tables import JobRow, TrialRow
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.family import VPadParams
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.part import Part
from api.models.search_plan import TimeEstimate, plan_job
from api.services import test_plans

FINALS = [("D1", "search", VPadParams(pad_width_mm=20, slack_mm=1, tip_height_mm=3)), ("STOCK", "stock", None), ("IMP", "imprint", None)]


@pytest.fixture
def add_job(db, profile_id):
    """add_job(job_id, status) -> a job written straight to the tables, with final trials D1, STOCK and IMP and D1 chosen
    for printing."""

    def add(job_id: str = "job1", status: str = "done", number: int = 42) -> str:
        part = Part()
        spec = JobSpec(name="Vial cap", part_id="part", cell_profile_id=profile_id, grasp=GraspChoice(angle_deg=0))
        plan = plan_job(
            part, spec, DEFAULT_PROFILE, sim_backend="mock", estimate=TimeEstimate(seconds=None, grasps_per_s=None, source="unknown")
        )
        job = {
            "id": job_id,
            "experiment_number": number,
            "name": spec.name,
            "status": status,
            "part_id": "part",
            "cell_profile_id": profile_id,
        }
        with db.session() as s:
            s.add(JobRow(**job, sim_backend="mock", spec=spec, part=part, plan=plan, print_designs=["D1"]))
            for n, (label, kind, params) in enumerate(FINALS, start=1):
                outcomes = {
                    "success_rate": 0.5,
                    "capture_radius_mm": None,
                    "n_grasps": 0,
                    "n_success": 0,
                    "held": [],
                    "in_hand": [],
                    "duration": 0,
                }
                params = params.model_dump() if params else None
                s.add(
                    TrialRow(
                        job_id=job_id, number=n, round=1, search="final", grid="final", kind=kind, label=label, params=params, **outcomes
                    )
                )
        return job_id

    return add


@pytest.fixture
def plan(client, add_job, db, config) -> dict:
    """A predicted plan of D1, IMP and STOCK with no random offsets: 75 rows each, 225."""
    created = test_plans.create_test_plan(db, config, add_job(), random_per_design=0, seed=1)
    test_plans.predict_test_plan(db, created.id, sim=MockSim())
    return test_plans.get_test_plan(db, created.job_id, created.id).model_dump()


def test_quick_log_a_planned_trial_and_an_extra(client, plan):
    url = f"/api/jobs/{plan['job_id']}/physical"

    planned = client.post(url, json={"trial_id": "T0001", "outcome": "held", "operator": "alec", "timestamp": "2026-10-20T14:30:00"})
    extra = client.post(url, json={"design_label": "D1", "offset_x_mm": 5, "offset_y_mm": 0, "outcome": "missed", "plan_id": plan["id"]})
    again = client.post(url, json={"trial_id": "T0001", "outcome": "missed"})

    assert planned.status_code == extra.status_code == again.status_code == 200
    assert (planned.json()["trial_id"], planned.json()["kind"], planned.json()["timestamp"]) == (
        "T0001",
        "pointwise",
        "2026-10-20T14:30:00",
    )
    assert (extra.json()["trial_id"], extra.json()["kind"], extra.json()["plan_id"]) == ("T0226", "extra", plan["id"])
    assert [h["outcome"] for h in again.json()["history"]] == ["held"]
    listed = client.get(url)
    assert listed.status_code == 200 and [t["trial_id"] for t in listed.json()] == ["T0001", "T0226"]


def test_quick_log_errors(client, plan, add_job):
    url = f"/api/jobs/{plan['job_id']}/physical"

    unknown = client.post(url, json={"trial_id": "T9999", "outcome": "held"})
    no_offset = client.post(url, json={"design_label": "D1", "outcome": "held"})
    no_outcome = client.post(url, json={"trial_id": "T0001"})
    bad_outcome = client.post(url, json={"trial_id": "T0001", "outcome": "dropped"})
    wrong_plan = client.post(url, json={"trial_id": "T0001", "outcome": "held", "plan_id": 99})
    missing = client.post("/api/jobs/nope/physical", json={"trial_id": "T0001", "outcome": "held"})
    not_done = client.post(f"/api/jobs/{add_job('job2', 'running', 43)}/physical", json={"trial_id": "T0001", "outcome": "held"})

    assert [r.status_code for r in (unknown, no_offset, no_outcome, bad_outcome, wrong_plan, missing, not_done)] == [
        422,
        422,
        422,
        422,
        404,
        404,
        409,
    ]
    assert unknown.json()["detail"] == "unknown trial_id T9999: it isn't in any of EXP-0042's test plans"
    assert no_offset.json()["detail"] == "no trial_id: a new row is logged as an extra trial, and needs offset_x_mm, offset_y_mm"


def test_validation(client, plan):
    job_id = plan["job_id"]
    assert client.get(f"/api/jobs/{job_id}/validation").json()["badge"] == "none"
    client.post(f"/api/jobs/{job_id}/physical", json={"trial_id": "T0001", "outcome": "held"})

    response = client.get(f"/api/jobs/{job_id}/validation")

    assert response.status_code == 200
    body = response.json()
    assert (body["badge"], body["sim_backend"], [d["design_label"] for d in body["designs"]]) == (
        "in_progress",
        "mock",
        ["D1", "IMP", "STOCK"],
    )
    assert set(body["designs"][0]) >= {"measured_success", "predicted_success", "wilson_low", "wilson_high", "summary", "offsets_agreed"}
    assert set(body["mismatches"][0]) == {
        "design_label",
        "kind",
        "offset_x_mm",
        "offset_y_mm",
        "yaw_deg",
        "predicted",
        "measured_rate",
        "repeats",
        "status",
    }
    assert body["curve_points"] == []
    assert client.get("/api/jobs/nope/validation").status_code == 404


def test_exports(client, plan, add_job):
    job_id = plan["job_id"]
    client.post(f"/api/jobs/{job_id}/physical", json={"trial_id": "T0001", "outcome": "held"})
    client.post(
        f"/api/jobs/{add_job('job2', number=43)}/physical",
        json={"design_label": "IMP", "offset_x_mm": 0, "offset_y_mm": 0, "outcome": "held"},
    )

    jsonl = client.get("/api/export/physical.jsonl", params={"job_id": job_id})
    every = client.get("/api/export/physical.jsonl")
    table = client.get("/api/export/physical.csv", params={"job_id": job_id})

    assert jsonl.status_code == every.status_code == table.status_code == 200
    assert jsonl.headers["content-type"] == "application/x-ndjson"
    assert jsonl.headers["content-disposition"] == 'attachment; filename="Vial-cap_EXP-0042_physical.jsonl"'
    (row,) = [json.loads(line) for line in jsonl.text.splitlines()]
    assert (row["experiment_id"], row["trial_id"], row["outcome"], row["predicted"]) == ("EXP-0042", "T0001", "held", True)
    assert [json.loads(line)["experiment_id"] for line in every.text.splitlines()] == ["EXP-0042", "EXP-0043"]
    assert every.headers["content-disposition"] == 'attachment; filename="physical.jsonl"'
    (parsed,) = csv.DictReader(io.StringIO(table.content.decode("utf-8-sig")))
    assert (parsed["trial_id"], parsed["predicted"]) == ("T0001", "true")
    assert client.get("/api/export/physical.csv", params={"job_id": "nope"}).status_code == 404
