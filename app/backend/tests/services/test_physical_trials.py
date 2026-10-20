import csv
import io
import json
from collections import Counter
from datetime import datetime

import pytest
from openpyxl import load_workbook

from api.db.tables import JobRow, TrialRow
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.error_model import ErrorModel
from api.models.family import VPadParams
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.outcome import Outcomes
from api.models.part import Part
from api.models.search_plan import TimeEstimate, plan_job
from api.models.task import Task
from api.models.validation import wilson_interval
from api.services import physical_trials, printed_fingers, spreadsheets, test_plans

FINALS = [
    ("D1", "search", VPadParams(pad_width_mm=20, slack_mm=1, tip_height_mm=3)),
    ("D2", "search", VPadParams(pad_width_mm=8, slack_mm=0.5, tip_height_mm=3)),
    ("STOCK", "stock", None),
    ("IMP", "imprint", None),
]
COLUMNS = test_plans.COLUMNS


def add_job(db, profile_id, *, job_id="job1", number=42, task=None, selection=("D1",)) -> str:
    """A finished job written straight to the tables: spec, part, plan, final-grid trials labelled D1, D2, STOCK and IMP
    (their outcomes don't matter here), and a print selection."""
    part = Part()
    spec = JobSpec(
        name="Vial cap", part_id="part", cell_profile_id=profile_id, grasp=GraspChoice(angle_deg=0), task=task or Task(), error=ErrorModel()
    )
    plan = plan_job(
        part, spec, DEFAULT_PROFILE, sim_backend="mock", estimate=TimeEstimate(seconds=None, grasps_per_s=None, source="unknown")
    )
    job = {"id": job_id, "experiment_number": number, "name": spec.name, "status": "done", "part_id": "part", "cell_profile_id": profile_id}
    with db.session() as s:
        s.add(JobRow(**job, sim_backend="mock", spec=spec, part=part, plan=plan, print_designs=list(selection)))
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
                TrialRow(job_id=job_id, number=n, round=1, search="final", grid="final", kind=kind, label=label, params=params, **outcomes)
            )
    return job_id


class FakeSim:
    """Holds wherever |dx| < 3.5 mm, the part centred in the hand except for dy."""

    backend, badge, url = "mock", "mock", None

    def run_batch(self, part, fingers, offsets, settings):
        held = [abs(o["dx"]) < 3.5 for o in offsets]
        in_hand = [(0.0, o["dy"], 0.0, 0.0, 0.0) if h else None for h, o in zip(held, offsets, strict=True)]
        return [Outcomes(held=held, in_hand=in_hand) for _ in fingers]


@pytest.fixture
def plan(db, config, profile_id, spawned):
    """A predicted plan of D1, IMP and STOCK: 25 point-wise offsets x 3 and 4 random ones each (79 rows each, 237)."""
    job_id = add_job(db, profile_id)
    created = test_plans.create_test_plan(db, config, job_id, random_per_design=4, seed=1)
    test_plans.predict_test_plan(db, created.id, sim=FakeSim())
    return test_plans.get_test_plan(db, job_id, created.id)


def upload_csv(db, plan, rows: list[dict], name: str = "results.csv"):
    return physical_trials.upload_results(db, plan.job_id, plan.id, name, spreadsheets.write_csv(COLUMNS, rows))


def trials(db, job_id="job1") -> dict:
    return {t.trial_id: t for t in physical_trials.list_trials(db, job_id)}


def fill_xlsx(content: bytes, outcomes: dict[str, dict], extra_rows: list[dict] = ()) -> bytes:
    """The downloaded workbook with cells filled in as an operator would: {trial_id: {column: value}}, then new rows."""
    workbook = load_workbook(io.BytesIO(content))
    sheet = workbook.active
    column = {cell.value: cell.column for cell in sheet[1]}
    for row in sheet.iter_rows(min_row=2):
        for name, value in outcomes.get(row[0].value, {}).items():
            sheet.cell(row[0].row, column[name], value)
    for values in extra_rows:
        r = sheet.max_row + 1
        for name, value in values.items():
            sheet.cell(r, column[name], value)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def test_an_xlsx_round_trip_logs_the_filled_rows_and_leaves_blank_ones_pending(db, plan):
    _, content = test_plans.plan_xlsx(db, plan.job_id, plan.id)
    filled = fill_xlsx(
        content,
        {
            "T0001": {"outcome": "held"},
            "T0002": {"outcome": "missed", "notes": "slid out", "operator": "alec", "video_link": "https://example.com/v/2"},
            "T0003": {"outcome": "skipped", "timestamp": datetime(2026, 10, 20, 14, 30)},
            "T0004": {"notes": "no outcome yet"},
        },
    )

    report = physical_trials.upload_results(db, plan.job_id, plan.id, "plan.xlsx", filled)

    assert (report.accepted, report.extras, report.unchanged, report.pending, report.errors) == (3, 0, 0, 237 - 3, [])
    logged = trials(db)
    assert sorted(logged) == ["T0001", "T0002", "T0003"]
    assert (logged["T0002"].outcome, logged["T0002"].notes, logged["T0002"].operator) == ("missed", "slid out", "alec")
    assert (logged["T0002"].kind, logged["T0002"].plan_id, logged["T0002"].design_label) == ("pointwise", plan.id, "D1")
    assert logged["T0003"].timestamp == "2026-10-20T14:30:00"
    assert datetime.fromisoformat(logged["T0001"].timestamp).tzinfo is not None  # filled in on upload
    again = load_workbook(io.BytesIO(test_plans.plan_xlsx(db, plan.job_id, plan.id)[1])).active
    assert [again.cell(r, 10).value for r in (2, 3, 4, 5)] == ["held", "missed", "skipped", None]  # logged outcomes come back


def test_a_csv_round_trip(db, plan):
    _, content = test_plans.plan_csv(db, plan.job_id, plan.id)
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    rows[0] |= {"outcome": "held", "operator": "7"}
    rows[1] |= {"outcome": "MISSED ", "timestamp": "10/20/2026 14:30"}  # as Excel re-saves a CSV

    report = upload_csv(db, plan, rows)

    assert (report.accepted, report.pending, report.errors) == (2, 235, [])
    logged = trials(db)
    assert (logged["T0001"].outcome, logged["T0001"].operator) == ("held", "7")
    assert (logged["T0002"].outcome, logged["T0002"].timestamp) == ("missed", "2026-10-20T14:30:00")


def test_a_semicolon_csv_in_windows_1252_reads_too(db, plan):
    content = "trial_id;outcome;notes\r\nT0001;held;café\r\n".encode("cp1252")

    report = physical_trials.upload_results(db, plan.job_id, plan.id, "results.csv", content)

    assert (report.accepted, report.errors) == (1, []) and trials(db)["T0001"].notes == "café"


def test_unknown_ids_and_bad_values_are_reported_by_row_and_the_rest_applied(db, config, plan):
    other = test_plans.create_test_plan(db, config, plan.job_id, random_per_design=0)
    rows = [
        {"trial_id": "T0001", "outcome": "held"},  # row 2: fine
        {"trial_id": "T9999", "outcome": "held"},  # 3
        {"trial_id": "T0002", "outcome": "hled", "in_tolerance": "maybe"},  # 4
        {"trial_id": "X12", "outcome": "held"},  # 5
        {"trial_id": "T0003", "design_id": "D2", "offset_x_mm": "1.5", "outcome": "held"},  # 6
        {"trial_id": "t1", "outcome": "missed"},  # 7: T0001 again
        {"trial_id": other.rows[0].trial_id, "outcome": "held"},  # 8: another plan's trial
        {"trial_id": "T0005", "experiment_id": "EXP-0007", "outcome": "held"},  # 9
        {"trial_id": "T0006", "repeat": "1.5", "timestamp": "yesterday", "outcome": "held"},  # 10
        {"design_id": "D1", "offset_x_mm": "abc", "offset_y_mm": "0", "outcome": "held"},  # 11
        {"trial_id": "T0007", "outcome": "skipped"},  # 12: fine
    ]

    report = upload_csv(db, plan, rows)

    errors = {e.row: (e.trial_id, e.reason) for e in report.errors}
    assert (report.accepted, sorted(trials(db))) == (2, ["T0001", "T0007"])
    assert errors[3] == ("T9999", "unknown trial_id T9999: it isn't in test plan 1")
    assert errors[4] == ("T0002", "outcome 'hled' isn't held, missed or skipped; in_tolerance 'maybe' isn't yes or no (or blank)")
    assert errors[5] == ("X12", "trial_id X12 isn't a trial ID (T0001, T0002, ...)")
    assert errors[6][1].startswith("design D2 isn't T0003's (D1); offset_x_mm 1.5 isn't T0003's (-1)")
    assert errors[6][1].endswith("to log a different offset, add it as a new row with trial_id blank")
    assert errors[7] == ("T0001", "T0001 is also on row 2; only that row is applied")
    assert errors[8] == (other.rows[0].trial_id, f"{other.rows[0].trial_id} is in test plan {other.id}, not this one ({plan.id})")
    assert errors[9] == ("T0005", "experiment_id EXP-0007 isn't this experiment (EXP-0042)")
    assert (
        errors[10][1] == "repeat '1.5' isn't a whole number from 1 up; timestamp 'yesterday' isn't a date and time (e.g. 2026-10-19 14:30)"
    )
    assert errors[11] == (
        None,
        "offset_x_mm 'abc' isn't a number; no trial_id: a new row is logged as an extra trial, and needs offset_x_mm",
    )
    assert sorted(errors) == [3, 4, 5, 6, 7, 8, 9, 10, 11]


def test_an_unreadable_upload_is_refused_whole(db, plan):
    with pytest.raises(spreadsheets.UnsupportedSpreadsheetError, match="save the sheet as .xlsx"):
        physical_trials.upload_results(db, plan.job_id, plan.id, "plan.xls", b"\xd0\xcf\x11\xe0")
    with pytest.raises(spreadsheets.SpreadsheetError, match="not a readable .xlsx file"):
        physical_trials.upload_results(db, plan.job_id, plan.id, "plan.xlsx", b"PK not really a zip")
    with pytest.raises(spreadsheets.SpreadsheetError, match="the header row has no outcome column"):
        physical_trials.upload_results(db, plan.job_id, plan.id, "plan.csv", b"trial_id,result\r\nT0001,held\r\n")
    assert trials(db) == {}


def test_uploading_again_overwrites_changes_and_keeps_the_old_value_in_history(db, plan):
    upload_csv(db, plan, [{"trial_id": "T0001", "outcome": "held", "operator": "alec"}])
    first = trials(db)["T0001"]

    same = upload_csv(db, plan, [{"trial_id": "T0001", "outcome": "held", "operator": "alec"}])
    changed = upload_csv(db, plan, [{"trial_id": "T0001", "outcome": "missed", "operator": "alec", "notes": "re-checked on video"}])
    blank = upload_csv(db, plan, [{"trial_id": "T0001", "operator": "alec"}])  # no outcome: leaves it as it is

    assert (same.accepted, same.unchanged) == (0, 1) and (changed.accepted, changed.unchanged) == (1, 0)
    assert (blank.accepted, blank.unchanged) == (0, 0)
    trial = trials(db)["T0001"]
    assert (trial.outcome, trial.notes) == ("missed", "re-checked on video")
    (old,) = trial.history
    assert old | {"replaced": None} == {
        "outcome": "held",
        "in_tolerance": None,
        "finger_id": None,
        "notes": "",
        "video_link": None,
        "operator": "alec",
        "timestamp": first.timestamp,
        "replaced": None,
    }
    assert old["replaced"] is not None


def test_new_rows_become_extra_trials_with_the_next_ids_once(db, plan):
    extra = {"design_id": "D1", "offset_x_mm": "5", "offset_y_mm": "-1.5", "outcome": "missed"}
    rows = [{"trial_id": "T0001", "outcome": "held"}, extra, dict(extra), extra | {"yaw_deg": "10", "outcome": "held"}]

    first = upload_csv(db, plan, rows)
    again = upload_csv(db, plan, rows)

    assert (first.accepted, first.extras, first.extra_trial_ids) == (4, 3, ["T0238", "T0239", "T0240"])
    assert (again.accepted, again.extras, again.unchanged) == (0, 0, 4)
    logged = trials(db)
    assert len(logged) == 4
    assert (logged["T0238"].kind, logged["T0238"].plan_id, logged["T0238"].offset_y_mm, logged["T0238"].yaw_deg) == (
        "extra",
        plan.id,
        -1.5,
        0,
    )
    assert logged["T0240"].yaw_deg == 10
    assert first.pending == again.pending == 236  # extras aren't planned trials
    _, content = test_plans.plan_csv(db, plan.job_id, plan.id)
    listed = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert [row["trial_id"] for row in listed[-3:]] == ["T0238", "T0239", "T0240"]  # downloads list them under their IDs
    assert upload_csv(db, plan, listed).unchanged == 4


def test_an_extra_needs_its_design_offset_and_outcome(db, plan):
    report = upload_csv(
        db,
        plan,
        [
            {"design_id": "D1", "offset_x_mm": "1"},
            {"design_id": "D2", "offset_x_mm": "1", "offset_y_mm": "0", "outcome": "held"},
            {"experiment_id": "EXP-0042"},  # nothing to log: skipped
        ],
    )

    assert [(e.row, e.reason) for e in report.errors] == [
        (2, "no trial_id: a new row is logged as an extra trial, and needs offset_y_mm, outcome"),
        (3, "design D2 isn't in this plan (D1, IMP, STOCK)"),
    ]
    assert report.accepted == 0


def test_the_quick_log_follows_the_same_rules(db, plan):
    planned = physical_trials.log_trial(db, plan.job_id, {"trial_id": "T0002", "outcome": "held", "operator": "alec"})
    extra = physical_trials.log_trial(db, plan.job_id, {"design_label": "IMP", "offset_x_mm": 2, "offset_y_mm": 2, "outcome": "missed"})
    planned_extra = physical_trials.log_trial(
        db, plan.job_id, {"design_label": "D1", "offset_x_mm": 2, "offset_y_mm": 2, "outcome": "missed"}, plan_id=plan.id
    )
    overwritten = physical_trials.log_trial(db, plan.job_id, {"trial_id": "T0002", "outcome": "missed"})

    assert (planned.trial_id, planned.kind, planned.plan_id, planned.outcome) == ("T0002", "pointwise", plan.id, "held")
    assert (extra.trial_id, extra.kind, extra.plan_id) == ("T0238", "extra", None)
    assert (planned_extra.trial_id, planned_extra.plan_id) == ("T0239", plan.id)
    assert overwritten.outcome == "missed" and [h["outcome"] for h in overwritten.history] == ["held"]
    with pytest.raises(physical_trials.PhysicalTrialError, match="unknown trial_id T9999: it isn't in any of EXP-0042's test plans"):
        physical_trials.log_trial(db, plan.job_id, {"trial_id": "T9999", "outcome": "held"})
    with pytest.raises(physical_trials.PhysicalTrialError, match="design D7 isn't in EXP-0042"):
        physical_trials.log_trial(db, plan.job_id, {"design_label": "D7", "offset_x_mm": 0, "offset_y_mm": 0, "outcome": "held"})
    with pytest.raises(physical_trials.PhysicalTrialError, match="outcome is required"):
        physical_trials.log_trial(db, plan.job_id, {"trial_id": "T0003"})


def test_a_printed_finger_is_named_on_its_trials(db, plan):
    printed_fingers.add_printed_finger(db, plan.job_id, design_label="D1", side="pair", material="PLA")

    upload_csv(
        db, plan, [{"trial_id": "T0001", "outcome": "held"}, {"trial_id": "T0002", "outcome": "held", "finger_id": "EXP-0042-D1-reprint"}]
    )

    logged = trials(db)
    assert (logged["T0001"].finger_id, logged["T0002"].finger_id) == ("EXP-0042-D1", "EXP-0042-D1-reprint")


def robot(planned, held) -> dict:
    """A logged row for a planned trial: held or missed."""
    return {"trial_id": planned.trial_id, "outcome": "held" if held else "missed"}


def test_validation_compares_the_sim_with_the_robot_offset_by_offset(db, plan):
    d1 = [row for row in plan.rows if row.design_label == "D1"]
    # The sim holds where |dx| < 3.5 mm; the robot only where |dx| < 2.5: the six point-wise offsets at |dx| = 3 disagree.
    upload_csv(db, plan, [robot(row, abs(row.offset_x_mm) < 2.5) for row in d1])

    result = physical_trials.validation(db, plan.job_id)

    assert (result.badge, result.sim_backend) == ("in_progress", "mock")
    d1_result, imp, stock = result.designs
    assert [d.design_label for d in result.designs] == ["D1", "IMP", "STOCK"]
    pointwise, random = d1[:75], d1[75:]
    measured = sum(abs(r.offset_x_mm) < 2.5 for r in d1)
    predicted = sum(abs(r.offset_x_mm) < 3.5 for r in d1)
    assert (d1_result.planned, d1_result.logged, d1_result.n, d1_result.skipped, d1_result.incomplete) == (79, 79, 79, 0, 0)
    assert d1_result.measured_success == pytest.approx(measured / 79) and d1_result.predicted_success == pytest.approx(predicted / 79)
    assert (d1_result.wilson_low, d1_result.wilson_high) == pytest.approx(wilson_interval(measured, 79))
    assert (d1_result.offsets, d1_result.offsets_compared, d1_result.offsets_agreed) == (25, 25, 19)
    assert d1_result.summary == "sim matched reality on 19 of 25 offsets"
    assert (imp.logged, imp.n, imp.measured_success, imp.wilson_low) == (0, 0, None, None)
    assert imp.summary == "no point-wise offsets tested yet"
    statuses = Counter((p.design_label, p.kind, p.status) for p in result.mismatches)
    assert statuses[("D1", "pointwise", "agreed")] == 19 and statuses[("D1", "pointwise", "sim_only")] == 6
    assert statuses[("STOCK", "pointwise", "pending")] == 25 and statuses[("IMP", "random", "pending")] == 4
    sim_only = {(p.offset_x_mm, p.offset_y_mm) for p in result.mismatches if p.status == "sim_only" and p.kind == "pointwise"}
    assert sim_only == {(3, 0), (-3, 0), (3, 3), (-3, 3), (-3, -3), (3, -3)}
    assert all(p.repeats == 3 and p.measured_rate in (0, 1) for p in result.mismatches if p.design_label == "D1" and p.kind == "pointwise")
    (curve,) = result.curve_points
    random_held = sum(abs(r.offset_x_mm) < 2.5 for r in random)
    assert (curve.design_label, curve.sigma_mm, curve.n) == ("D1", 3.0, 4)
    assert (curve.measured_success, curve.wilson_low, curve.wilson_high) == pytest.approx(
        (random_held / 4, *wilson_interval(random_held, 4))
    )
    assert curve.predicted_success == pytest.approx(sum(abs(r.offset_x_mm) < 3.5 for r in random) / 4)
    assert len(pointwise) == 75


def test_repeats_vote_and_skipped_trials_dont_count(db, plan):
    rows = {(r.offset, r.repeat): r for r in plan.rows if r.design_label == "STOCK" and r.kind == "pointwise"}
    centre, far = (0.0, 0.0, 0.0), (6.0, 0.0, 0.0)  # the sim holds the centre, misses at 6 mm
    upload_csv(
        db,
        plan,
        [
            robot(rows[centre, 1], True),
            robot(rows[centre, 2], False),
            {"trial_id": rows[centre, 3].trial_id, "outcome": "skipped"},  # one each way: mixed
            robot(rows[far, 1], True),
            robot(rows[far, 2], True),
            robot(rows[far, 3], False),  # the robot's majority holds where the sim missed
        ],
    )

    result = physical_trials.validation(db, plan.job_id)

    stock = next(d for d in result.designs if d.design_label == "STOCK")
    points = {(p.offset_x_mm, p.offset_y_mm): p for p in result.mismatches if p.design_label == "STOCK" and p.kind == "pointwise"}
    assert (points[0, 0].status, points[0, 0].measured_rate, points[0, 0].repeats) == ("mixed", 0.5, 2)
    assert (points[6, 0].status, points[6, 0].predicted, points[6, 0].measured_rate) == ("real_only", False, pytest.approx(2 / 3))
    assert (stock.logged, stock.skipped, stock.n, stock.measured_success) == (6, 1, 5, pytest.approx(3 / 5))
    assert stock.summary == "sim matched reality on 0 of 2 offsets (23 not compared yet)"


def test_place_and_insert_count_in_tolerance_and_leave_blanks_out(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id, task=Task(kind="place", offset_tolerance_mm=2))
    created = test_plans.create_test_plan(db, config, job_id, random_per_design=0, seed=1)
    test_plans.predict_test_plan(db, created.id, sim=FakeSim())
    plan = test_plans.get_test_plan(db, job_id, created.id)
    d1 = [row for row in plan.rows if row.design_label == "D1"]

    upload_csv(
        db,
        plan,
        [
            {"trial_id": d1[0].trial_id, "outcome": "held", "in_tolerance": "yes"},
            {"trial_id": d1[1].trial_id, "outcome": "held", "in_tolerance": "no"},
            {"trial_id": d1[2].trial_id, "outcome": "held"},  # in_tolerance blank: incomplete
            {"trial_id": d1[3].trial_id, "outcome": "missed"},
        ],
    )

    design = physical_trials.validation(db, job_id).designs[0]
    assert (design.logged, design.incomplete, design.n, design.measured_success) == (4, 1, 3, pytest.approx(1 / 3))
    assert trials(db, job_id)[d1[0].trial_id].in_tolerance is True


def test_the_badge_goes_none_in_progress_validated(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)
    assert physical_trials.physical_badge(db, job_id) == "none"
    plan = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=1)
    assert physical_trials.physical_badge(db, job_id) == "none"

    upload_csv(db, plan, [{"trial_id": plan.rows[0].trial_id, "outcome": "held"}])
    assert physical_trials.physical_badge(db, job_id) == "in_progress"

    upload_csv(db, plan, [{"trial_id": row.trial_id, "outcome": "skipped"} for row in plan.rows[1:]])
    assert physical_trials.physical_badge(db, job_id) == physical_trials.validation(db, job_id).badge == "validated"

    second = test_plans.create_test_plan(db, config, job_id, pointwise_repeats=1, random_per_design=0)
    assert physical_trials.physical_badge(db, job_id) == "in_progress"  # every plan counts
    upload_csv(db, second, [{"trial_id": row.trial_id, "outcome": "missed"} for row in second.rows])
    assert physical_trials.physical_badge(db, job_id) == "validated"


def test_extras_alone_are_in_progress(db, config, profile_id, spawned):
    job_id = add_job(db, profile_id)

    physical_trials.log_trial(db, job_id, {"design_label": "D1", "offset_x_mm": 0, "offset_y_mm": 0, "outcome": "held"})

    assert physical_trials.physical_badge(db, job_id) == "in_progress"
    (design,) = physical_trials.validation(db, job_id).designs
    assert (design.design_label, design.planned, design.extras, design.n, design.summary) == (
        "D1",
        0,
        1,
        0,
        "no point-wise offsets planned",
    )


def test_exports_carry_the_prediction_next_to_the_outcome(db, config, profile_id, plan):
    upload_csv(
        db,
        plan,
        [{"trial_id": "T0001", "outcome": "held"}, {"design_id": "D1", "offset_x_mm": "9", "offset_y_mm": "0", "outcome": "missed"}],
    )
    add_job(db, profile_id, job_id="job2", number=43)
    physical_trials.log_trial(db, "job2", {"design_label": "IMP", "offset_x_mm": 0, "offset_y_mm": 0, "outcome": "held"})

    rows = physical_trials.export_rows(db, plan.job_id)
    every = physical_trials.export_rows(db)
    content = physical_trials.export_csv(db, plan.job_id).decode("utf-8-sig")

    assert [(r["experiment_id"], r["trial_id"], r["predicted"], r["outcome"]) for r in rows] == [
        ("EXP-0042", "T0001", True, "held"),
        ("EXP-0042", "T0238", None, "missed"),
    ]
    assert tuple(rows[0]) == physical_trials.EXPORT_COLUMNS and rows[0]["sim_backend"] == "mock" and rows[0]["history"] == []
    assert [r["experiment_id"] for r in every] == ["EXP-0042", "EXP-0042", "EXP-0043"]
    parsed = list(csv.DictReader(io.StringIO(content)))
    assert tuple(parsed[0]) == physical_trials.EXPORT_COLUMNS
    assert (parsed[0]["predicted"], parsed[0]["history"], parsed[1]["predicted"]) == ("true", "[]", "")
    assert json.loads(json.dumps(rows))  # plain JSON
    assert physical_trials.export_file_name(db, plan.job_id, "csv") == "Vial-cap_EXP-0042_physical.csv"
    with pytest.raises(physical_trials.JobNotFoundError):
        physical_trials.export_rows(db, "nope")
