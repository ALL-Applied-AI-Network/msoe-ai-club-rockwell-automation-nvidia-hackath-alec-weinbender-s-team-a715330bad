import pytest

from api.db.tables import JobRow, TrialRow
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.family import VPadParams
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.part import Part
from api.models.search_plan import TimeEstimate, plan_job

FINALS = [("D1", "search", VPadParams(pad_width_mm=20, slack_mm=1, tip_height_mm=3)), ("STOCK", "stock", None), ("IMP", "imprint", None)]


@pytest.fixture
def add_job(db, profile_id):
    """add_job(job_id, status) -> a job written straight to the tables, with final trials D1, STOCK and IMP."""

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
            s.add(JobRow(**job, sim_backend="mock", spec=spec, part=part, plan=plan))
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


def test_put_print_selection(client, add_job):
    job_id = add_job()

    response = client.put(f"/api/jobs/{job_id}/print-selection", json={"designs": ["D1", "STOCK"]})

    assert response.status_code == 200
    assert response.json() == {
        "designs": ["D1"],
        "printed": ["D1", "IMP"],
        "tested": ["D1", "IMP", "STOCK"],
        "available": ["D1", "IMP", "STOCK"],
    }
    assert client.get(f"/api/jobs/{job_id}/print-selection").json() == response.json()


def test_print_selection_errors(client, add_job):
    job_id, running = add_job(), add_job("job2", "running", 43)

    unknown = client.put(f"/api/jobs/{job_id}/print-selection", json={"designs": ["D4"]})
    not_done = client.put(f"/api/jobs/{running}/print-selection", json={"designs": ["D1"]})
    missing = client.put("/api/jobs/nope/print-selection", json={"designs": []})
    malformed = client.put(f"/api/jobs/{job_id}/print-selection", json={"designs": "D1"})

    assert [r.status_code for r in (unknown, not_done, missing, malformed)] == [422, 409, 404, 422]
    assert unknown.json()["detail"] == "EXP-0042 has no design D4; its final test has D1, IMP, STOCK"
    assert not_done.json()["detail"].startswith("EXP-0043 is running")


def test_record_and_list_printed_fingers(client, add_job):
    url = f"/api/jobs/{add_job()}/printed-fingers"

    left = client.post(url, json={"design_label": "D1", "side": "L", "material": "PLA", "print_date": "2026-10-20"})
    pair = client.post(url, json={"design_label": "IMP", "material": "PETG"})

    assert (left.status_code, pair.status_code) == (201, 201)
    assert (left.json()["finger_id"], left.json()["print_date"], pair.json()["finger_id"]) == (
        "EXP-0042-D1-L",
        "2026-10-20",
        "EXP-0042-IMP",
    )
    assert set(left.json()) == {"id", "job_id", "finger_id", "design_label", "side", "material", "print_date", "notes", "created"}
    assert client.get(url).json() == [left.json(), pair.json()]


def test_printed_finger_errors(client, add_job):
    url = f"/api/jobs/{add_job()}/printed-fingers"

    stock = client.post(url, json={"design_label": "STOCK", "material": "PLA"})
    no_material = client.post(url, json={"design_label": "D1"})
    bad_side = client.post(url, json={"design_label": "D1", "material": "PLA", "side": "left"})
    bad_date = client.post(url, json={"design_label": "D1", "material": "PLA", "print_date": "last week"})

    assert [r.status_code for r in (stock, no_material, bad_side, bad_date)] == [422] * 4
    assert stock.json()["detail"].startswith("STOCK is the aluminium fingers")
    assert client.get("/api/jobs/nope/printed-fingers").status_code == 404
    assert (
        client.post(
            f"/api/jobs/{add_job('job2', 'failed', 43)}/printed-fingers", json={"design_label": "D1", "material": "PLA"}
        ).status_code
        == 409
    )
