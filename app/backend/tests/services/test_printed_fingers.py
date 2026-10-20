from datetime import date

import pytest

from api.db.tables import JobRow, TrialRow
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.family import VPadParams
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.part import Part
from api.models.search_plan import TimeEstimate, plan_job
from api.services import jobs, printed_fingers

FINALS = [
    ("D1", "search", VPadParams(pad_width_mm=20, slack_mm=1, tip_height_mm=3)),
    ("D2", "search", VPadParams(pad_width_mm=8, slack_mm=0.5, tip_height_mm=3)),
    ("STOCK", "stock", None),
    ("IMP", "imprint", None),
]


def add_job(db, profile_id, *, job_id="job1", number=42, status="done") -> str:
    """A job as the optimizer leaves it, written straight to the tables: its spec, part and plan, and final-grid trials
    labelled D1, D2, STOCK and IMP (their outcomes don't matter here)."""
    part = Part()
    spec = JobSpec(name="Vial cap: first try", part_id="part", cell_profile_id=profile_id, grasp=GraspChoice(angle_deg=0))
    plan = plan_job(
        part, spec, DEFAULT_PROFILE, sim_backend="mock", estimate=TimeEstimate(seconds=None, grasps_per_s=None, source="unknown")
    )
    with db.session() as s:
        s.add(
            JobRow(
                id=job_id,
                experiment_number=number,
                name=spec.name,
                status=status,
                part_id="part",
                cell_profile_id=profile_id,
                sim_backend="mock",
                spec=spec,
                part=part,
                plan=plan,
            )
        )
        for n, (label, kind, params) in enumerate(FINALS, start=1):
            params = params.model_dump() if params else None
            search = "vpad" if params else "baseline"
            outcomes = {
                "success_rate": 0.5,
                "capture_radius_mm": None,
                "n_grasps": 0,
                "n_success": 0,
                "held": [],
                "in_hand": [],
                "duration": 0.0,
            }
            s.add(
                TrialRow(job_id=job_id, number=n, round=1, search=search, grid="final", kind=kind, label=label, params=params, **outcomes)
            )
    return job_id


def test_the_selection_is_checked_against_the_final_labels_and_stored_on_the_job(db, profile_id):
    job_id = add_job(db, profile_id)

    selection = printed_fingers.set_print_selection(db, job_id, ["D2", "STOCK", "D2", "IMP"])

    assert selection.designs == ["D2"] and printed_fingers.load_job(db, job_id).print_designs == ["D2"]
    assert (selection.printed, selection.tested) == (["D2", "IMP"], ["D2", "IMP", "STOCK"])
    assert selection.available == ["D1", "D2", "IMP", "STOCK"]
    assert printed_fingers.get_print_selection(db, job_id) == selection
    with pytest.raises(printed_fingers.DesignLabelError, match="EXP-0042 has no design D7; its final test has D1, D2, IMP, STOCK"):
        printed_fingers.set_print_selection(db, job_id, ["D1", "D7"])
    assert printed_fingers.load_job(db, job_id).print_designs == ["D2"]


def test_an_empty_selection_tests_the_baselines_only(db, profile_id):
    job_id = add_job(db, profile_id)

    selection = printed_fingers.set_print_selection(db, job_id, [])

    assert (selection.designs, selection.printed, selection.tested) == ([], ["IMP"], ["IMP", "STOCK"])


def test_selection_and_fingers_need_a_finished_job(db, profile_id):
    job_id = add_job(db, profile_id, status="running")

    with pytest.raises(printed_fingers.JobNotDoneError, match="EXP-0042 is running"):
        printed_fingers.set_print_selection(db, job_id, ["D1"])
    with pytest.raises(printed_fingers.JobNotDoneError):
        printed_fingers.add_printed_finger(db, job_id, design_label="D1", material="PLA")
    with pytest.raises(jobs.JobNotFoundError):
        printed_fingers.set_print_selection(db, "nope", ["D1"])


def test_a_printed_finger_gets_its_engraved_id(db, profile_id):
    job_id = add_job(db, profile_id)

    left = printed_fingers.add_printed_finger(db, job_id, design_label="D1", side="L", material="PLA", print_date=date(2026, 10, 20))
    pair = printed_fingers.add_printed_finger(db, job_id, design_label="IMP", material="PETG", notes="0.2 mm layers")

    assert (left.finger_id, left.side, left.print_date) == ("EXP-0042-D1-L", "L", "2026-10-20")
    assert (pair.finger_id, pair.side, pair.material, pair.notes) == ("EXP-0042-IMP", "pair", "PETG", "0.2 mm layers")
    assert printed_fingers.list_printed_fingers(db, job_id) == [left, pair]
    assert printed_fingers.trial_finger_ids(db, printed_fingers.load_job(db, job_id)) == {"D1": "EXP-0042-D1", "IMP": "EXP-0042-IMP"}


def test_stock_and_unknown_designs_cant_be_printed(db, profile_id):
    job_id = add_job(db, profile_id)

    with pytest.raises(printed_fingers.DesignLabelError, match="STOCK is the aluminium fingers"):
        printed_fingers.add_printed_finger(db, job_id, design_label="STOCK", material="PLA")
    with pytest.raises(printed_fingers.DesignLabelError, match="no design D9"):
        printed_fingers.add_printed_finger(db, job_id, design_label="D9", material="PLA")
    with pytest.raises(printed_fingers.PrintedFingerError, match="material is required"):
        printed_fingers.add_printed_finger(db, job_id, design_label="D1", material="  ")
    assert printed_fingers.list_printed_fingers(db, job_id) == []


def test_final_designs_rebuild_each_label(db, profile_id):
    job_id = add_job(db, profile_id)

    designs = printed_fingers.final_designs(db, job_id)

    assert list(designs) == ["D1", "D2", "IMP", "STOCK"]
    assert (designs["D1"].kind, designs["D1"].params) == ("search", FINALS[0][2])
    assert designs["IMP"].kind == "imprint" and designs["STOCK"] is None
