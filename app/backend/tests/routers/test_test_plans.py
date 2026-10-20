import csv
import io

import pytest
from openpyxl import load_workbook

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
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
def plan(client, add_job, db) -> dict:
    """A plan made through the API (2 random offsets per design: 77 rows each, 231), then predicted by the mock."""
    response = client.post(f"/api/jobs/{add_job()}/test-plans", json={"random_per_design": 2, "seed": 4})
    assert response.status_code == 201, response.text
    test_plans.predict_test_plan(db, response.json()["id"], sim=MockSim())
    return response.json()


def test_create_a_plan(client, add_job, spawned):
    job_id = add_job()

    response = client.post(f"/api/jobs/{job_id}/test-plans", json={"pointwise_repeats": 1, "random_per_design": 0, "seed": 9})

    assert response.status_code == 201
    body = response.json()
    assert (body["designs"], body["seed"], body["prediction_status"], body["logged"], body["logged_trials"]) == (
        ["D1", "IMP", "STOCK"],
        9,
        "pending",
        0,
        [],
    )
    assert len(body["rows"]) == 75 and body["rows"][0] == {
        "trial_id": "T0001",
        "design_label": "D1",
        "finger_id": None,
        "kind": "pointwise",
        "offset_x_mm": 0.0,
        "offset_y_mm": 0.0,
        "yaw_deg": 0.0,
        "repeat": 1,
        "predicted": None,
        "predicted_in_tolerance": None,
    }
    assert spawned == [(job_id, "predict", str(body["id"]))]
    assert client.post(f"/api/jobs/{job_id}/test-plans", json={}).json()["rows"][0]["trial_id"] == "T0076"  # defaults; IDs go on


def test_create_errors(client, add_job):
    job_id = add_job()

    not_done = client.post(f"/api/jobs/{add_job('job2', 'running', 43)}/test-plans", json={})
    missing = client.post("/api/jobs/nope/test-plans", json={})
    no_repeats = client.post(f"/api/jobs/{job_id}/test-plans", json={"pointwise_repeats": 0})
    too_many = client.post(f"/api/jobs/{job_id}/test-plans", json={"random_per_design": 100000})

    assert [r.status_code for r in (not_done, missing, no_repeats, too_many)] == [409, 404, 422, 422]


def test_list_and_read_plans(client, plan, db):
    job_id = plan["job_id"]
    client.post(f"/api/jobs/{job_id}/physical", json={"trial_id": "T0001", "outcome": "held"})
    client.post(
        f"/api/jobs/{job_id}/physical",
        json={"design_label": "D1", "offset_x_mm": 9, "offset_y_mm": 0, "outcome": "missed", "plan_id": plan["id"]},
    )

    listed = client.get(f"/api/jobs/{job_id}/test-plans")
    one = client.get(f"/api/jobs/{job_id}/test-plans/{plan['id']}")

    assert listed.status_code == one.status_code == 200
    (summary,) = listed.json()
    assert "rows" not in summary and (summary["planned"], summary["logged"], summary["extras"], summary["prediction_status"]) == (
        231,
        1,
        1,
        "done",
    )
    body = one.json()
    assert (len(body["rows"]), body["logged"], body["extras"]) == (231, 1, 1)
    assert [t["trial_id"] for t in body["logged_trials"]] == ["T0001", "T0232"]
    assert all(row["predicted"] is not None for row in body["rows"])
    assert client.get(f"/api/jobs/{job_id}/test-plans/{plan['id'] + 1}").status_code == 404
    assert client.get("/api/jobs/nope/test-plans").status_code == 404


def test_download_xlsx_and_csv(client, plan):
    base = f"/api/jobs/{plan['job_id']}/test-plans/{plan['id']}"

    xlsx = client.get(f"{base}.xlsx")
    blind = client.get(f"{base}.csv")
    shown = client.get(f"{base}.csv", params={"include_predicted": "true"})

    assert xlsx.status_code == blind.status_code == shown.status_code == 200
    assert xlsx.headers["content-type"] == XLSX
    assert xlsx.headers["content-disposition"] == 'attachment; filename="Vial-cap_EXP-0042_test-plan-1.xlsx"'
    assert load_workbook(io.BytesIO(xlsx.content)).active.max_row == 1 + 231
    assert blind.headers["content-type"].startswith("text/csv")
    assert blind.headers["content-disposition"] == 'attachment; filename="Vial-cap_EXP-0042_test-plan-1.csv"'
    rows = list(csv.DictReader(io.StringIO(blind.content.decode("utf-8-sig"))))
    assert len(rows) == 231 and {r["predicted"] for r in rows} == {""}
    assert {r["predicted"] for r in csv.DictReader(io.StringIO(shown.content.decode("utf-8-sig")))} == {"yes", "no"}
    assert client.get(f"/api/jobs/{plan['job_id']}/test-plans/99.xlsx").status_code == 404


def test_upload_a_filled_xlsx(client, plan):
    base = f"/api/jobs/{plan['job_id']}/test-plans/{plan['id']}"
    workbook = load_workbook(io.BytesIO(client.get(f"{base}.xlsx").content))
    sheet = workbook.active
    sheet["J2"], sheet["J3"], sheet["A4"], sheet["J4"] = "held", "missed", "T9999", "held"
    sheet.append([None, None, "D1", None, 5, 0, 0, None, None, "missed"])
    out = io.BytesIO()
    workbook.save(out)

    response = client.post(f"{base}/upload", files={"file": ("filled.xlsx", out.getvalue(), XLSX)})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "accepted": 3,
        "extras": 1,
        "extra_trial_ids": ["T0232"],
        "unchanged": 0,
        "pending": 229,
        "errors": [{"row": 4, "trial_id": "T9999", "reason": "unknown trial_id T9999: it isn't in test plan 1"}],
    }


def test_upload_errors(client, plan):
    url = f"/api/jobs/{plan['job_id']}/test-plans/{plan['id']}/upload"

    old_excel = client.post(url, files={"file": ("plan.xls", b"\xd0\xcf\x11\xe0", "application/vnd.ms-excel")})
    unreadable = client.post(url, files={"file": ("plan.xlsx", b"PK nope", XLSX)})
    no_header = client.post(url, files={"file": ("plan.csv", b"trial_id\r\nT0001\r\n", "text/csv")})
    no_file = client.post(url, data={})
    no_plan = client.post(
        f"/api/jobs/{plan['job_id']}/test-plans/99/upload", files={"file": ("plan.csv", b"trial_id,outcome\r\n", "text/csv")}
    )

    assert [r.status_code for r in (old_excel, unreadable, no_header, no_file, no_plan)] == [415, 422, 422, 422, 404]
    assert no_header.json()["detail"].startswith("the header row has no outcome column")


def test_predict_again(client, plan, spawned):
    response = client.post(f"/api/jobs/{plan['job_id']}/test-plans/{plan['id']}/predict")

    assert response.status_code == 200 and response.json()["prediction_status"] == "pending"
    assert spawned[-1] == (plan["job_id"], "predict", str(plan["id"]))
