"""Grasp attempts on the real arm, logged against a job's test plans (spreadsheet round-trip) or as extra trials, and
compared with the sim's predictions (docs/notes/input-flow-backend-plan.md, 4.8). validation() and physical_badge() are
what the results page and the job cards call.

Logging rules, the same for an uploaded sheet and the one-trial quick log:
- A row with a trial_id logs that planned trial (or re-logs an extra one). Unknown IDs, and IDs from another plan than
  the one uploaded, are rejected with the row number and reason. The design and offset cells, when filled, must match
  the plan, so a shifted paste is caught instead of logging outcomes against the wrong offsets.
- A blank outcome leaves the trial pending; it never clears an outcome already logged.
- Logging a trial again overwrites it. If anything changed, the old values go to its history first (oldest first);
  identical rows change nothing, so the same sheet can be uploaded again and again.
- A row without a trial_id is an extra trial: it needs its design, offset and outcome, and gets the job's next trial ID.
  Uploading the same sheet again doesn't add its extra rows twice: a blank-ID row identical to an extra already logged
  from this plan is that extra (one for one). A downloaded sheet lists extras under their IDs anyway.
- Every value is checked: outcome (held, missed, skipped), in_tolerance (yes, no or blank), numbers, the timestamp (ISO,
  or month/day/year as Excel writes it). A blank timestamp is filled in with the time of the upload.
Valid rows are applied even when other rows have errors.
"""

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, func, select

from api.clients.database import DatabaseClient
from api.db.tables import JobRow, PhysicalTrialRow, PrintedFingerRow, TestPlanRow
from api.models.job import Job, experiment_id
from api.models.physical_trial import LOGGED_FIELDS, TRIAL_OUTCOMES, LogReport, PhysicalTrial, RowError
from api.models.task import TaskKind
from api.models.test_plan import PlannedTrial, TestPlan, offset_key, trial_id, trial_number
from api.models.validation import CurvePoint, DesignValidation, MismatchPoint, MismatchStatus, PhysicalBadge, Validation, wilson_interval
from api.services import printed_fingers, spreadsheets, test_plans
from api.services.jobs import JobNotFoundError

logger = logging.getLogger(__name__)

SHEET_FIELDS = {"design_id": "design_label"}  # spreadsheet column -> the field it fills, where they differ
REQUIRED_COLUMNS = ("trial_id", "outcome")
OFFSET_MATCH_MM = 0.005  # a filled-in offset within this of the plan's is the plan's (spreadsheets round numbers)
TIME_FORMATS = ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y")  # Excel, US
EXPORT_COLUMNS = (
    "experiment_id",
    "job_id",
    "plan_id",
    "trial_id",
    "design_label",
    "finger_id",
    "kind",
    "offset_x_mm",
    "offset_y_mm",
    "yaw_deg",
    "repeat",
    "predicted",
    "predicted_in_tolerance",
    "outcome",
    "in_tolerance",
    "notes",
    "video_link",
    "operator",
    "timestamp",
    "sim_backend",
    "history",
)


class PhysicalTrialError(ValueError):
    """A trial that can't be logged as sent: an unknown trial ID, a bad value, an extra trial without its design or
    offset. The message says which and why."""


@dataclass(frozen=True)
class _Scope:
    """What a row is checked against."""

    job: Job
    plan_id: int | None  # the plan uploaded; None for the quick log, which takes a trial of any plan
    planned: dict[str, tuple[int, PlannedTrial]]  # trial ID -> (plan id, planned trial), every plan of the job
    extras: dict[str, PhysicalTrial]  # trial ID -> extra trial already logged
    designs: list[str]  # the designs a new extra trial can be for
    finger_ids: dict[str, str]  # design -> the pair's ID, for designs with a printed finger


@dataclass
class _Entry:
    """One checked row, ready to log."""

    row: int
    trial_id: str | None  # None: a new extra trial
    plan_id: int | None
    kind: str
    design_label: str
    finger_id: str | None
    finger_given: bool  # typed in, rather than filled from the plan or the printed fingers
    offset_x_mm: float
    offset_y_mm: float
    yaw_deg: float
    repeat: int
    outcome: str | None  # None: pending
    in_tolerance: bool | None
    notes: str
    video_link: str | None
    operator: str | None
    timestamp: str | None  # None: filled in when logged


def upload_results(db: DatabaseClient, job_id: str, plan_id: int, filename: str, content: bytes) -> LogReport:
    """Log a filled-in test plan (.xlsx or .csv, as downloaded): every valid row is applied, every invalid one reported."""
    plan = test_plans.get_test_plan(db, job_id, plan_id)
    job = printed_fingers.load_job(db, job_id)
    table = spreadsheets.read_rows(filename, content, required=REQUIRED_COLUMNS)
    scope = _scope(db, job, plan_id, plan.designs)
    entries, errors, seen = [], [], {}
    for row, values in table:
        checked = _check(row, {SHEET_FIELDS.get(name, name): value for name, value in values.items()}, scope)
        if checked is None:
            continue
        if isinstance(checked, RowError):
            errors.append(checked)
        elif checked.trial_id is not None and checked.trial_id in seen:
            errors.append(
                RowError(
                    row=row,
                    trial_id=checked.trial_id,
                    reason=f"{checked.trial_id} is also on row {seen[checked.trial_id]}; only that row is applied",
                )
            )
        else:
            if checked.trial_id is not None:
                seen[checked.trial_id] = row
            entries.append(checked)
    applied = _apply(db, scope, entries, match_extras=True)
    with db.session() as s:
        done = set(
            s.scalars(select(PhysicalTrialRow.trial_id).where(PhysicalTrialRow.job_id == job_id, PhysicalTrialRow.plan_id == plan_id))
        )
    report = LogReport(
        accepted=sum(1 for status, _ in applied if status != "unchanged"),
        extras=sum(1 for status, _ in applied if status == "extra"),
        extra_trial_ids=[trial.trial_id for status, trial in applied if status == "extra"],
        unchanged=sum(1 for status, _ in applied if status == "unchanged"),
        pending=sum(1 for planned in plan.rows if planned.trial_id not in done),
        errors=errors,
    )
    logger.info(
        "Job %s, test plan %s: %s uploaded: %d accepted (%d extra), %d unchanged, %d pending, %d rows with errors",
        job_id,
        plan_id,
        filename,
        report.accepted,
        report.extras,
        report.unchanged,
        report.pending,
        len(errors),
    )
    return report


def log_trial(db: DatabaseClient, job_id: str, values: Mapping[str, Any], *, plan_id: int | None = None) -> PhysicalTrial:
    """The quick log: one trial, by its trial_id (of any of the job's plans, or an extra one), or a new extra trial with
    its design and offset (and plan_id, if it belongs with a plan). values uses the domain names (design_label, ...)."""
    job = printed_fingers.done_job(db, job_id)
    if plan_id is not None:
        designs = test_plans.get_test_plan(db, job_id, plan_id).designs
    else:
        designs = list(printed_fingers.final_designs(db, job_id))
    scope = _scope(db, job, plan_id, designs)
    checked = _check(0, values, scope)
    if isinstance(checked, RowError):
        raise PhysicalTrialError(checked.reason)
    if checked is None or checked.outcome is None:
        raise PhysicalTrialError("outcome is required: held, missed or skipped")
    ((status, trial),) = _apply(db, scope, [checked], match_extras=False)
    logger.info("Job %s: trial %s %s (%s)", job_id, trial.trial_id, trial.outcome, status)
    return trial


def list_trials(db: DatabaseClient, job_id: str | None = None, *, plan_id: int | None = None) -> list[PhysicalTrial]:
    """The job's trials (of one plan, if given) in the order they were logged, or every job's when job_id is None."""
    query = select(PhysicalTrialRow).order_by(PhysicalTrialRow.id)
    if job_id is not None:
        query = query.where(PhysicalTrialRow.job_id == job_id)
    if plan_id is not None:
        query = query.where(PhysicalTrialRow.plan_id == plan_id)
    with db.session() as s:
        return [PhysicalTrial.model_validate(row) for row in s.scalars(query)]


def validation(db: DatabaseClient, job_id: str) -> Validation:
    """Predicted vs measured for every tested design of the job, across all its test plans (see api/models/validation.py
    for what counts as a success)."""
    job = printed_fingers.load_job(db, job_id)
    with db.session() as s:
        plans = [
            TestPlan.model_validate(row)
            for row in s.scalars(select(TestPlanRow).where(TestPlanRow.job_id == job_id).order_by(TestPlanRow.id))
        ]
        trials = {
            row.trial_id: PhysicalTrial.model_validate(row)
            for row in s.scalars(select(PhysicalTrialRow).where(PhysicalTrialRow.job_id == job_id))
        }
        fingers = list(
            s.execute(select(PrintedFingerRow.design_label, PrintedFingerRow.finger_id).where(PrintedFingerRow.job_id == job_id))
        )
    planned = [row for plan in plans for row in plan.rows]
    badge = _badge(len(planned), len(trials), sum(1 for trial in trials.values() if trial.kind != "extra"))
    labels = sorted(
        {row.design_label for row in planned} | {trial.design_label for trial in trials.values()}, key=printed_fingers.label_order
    )
    out = Validation(badge=badge, sim_backend=job.sim_backend)
    for label in labels:
        rows = [row for row in planned if row.design_label == label]
        design, points, curve = _design_validation(
            job,
            label,
            rows,
            trials,
            finger_ids=[fid for design_label, fid in fingers if design_label == label],
            extras=sum(1 for trial in trials.values() if trial.kind == "extra" and trial.design_label == label),
        )
        out.designs.append(design)
        out.mismatches += points
        out.curve_points += curve
    return out


def physical_badge(db: DatabaseClient, job_id: str) -> PhysicalBadge:
    """none while nothing is logged; validated when every planned trial of every plan has an outcome (held, missed or
    skipped); in_progress otherwise. One query, for the job cards."""
    planned = (
        select(func.coalesce(func.sum(func.json_array_length(TestPlanRow.rows, type_=Integer)), 0))
        .where(TestPlanRow.job_id == job_id)
        .scalar_subquery()
    )
    logged = select(func.count(PhysicalTrialRow.id)).where(PhysicalTrialRow.job_id == job_id).scalar_subquery()
    logged_planned = (
        select(func.count(PhysicalTrialRow.id)).where(PhysicalTrialRow.job_id == job_id, PhysicalTrialRow.kind != "extra").scalar_subquery()
    )
    with db.session() as s:
        n_planned, n_logged, n_logged_planned = s.execute(select(planned, logged, logged_planned)).one()
    return _badge(n_planned, n_logged, n_logged_planned)


def export_rows(db: DatabaseClient, job_id: str | None = None) -> list[dict[str, Any]]:
    """Every logged trial (of one job, or all), with its experiment ID and the sim's prediction for it, by job and trial
    ID."""
    jobs_query = select(JobRow.id, JobRow.experiment_number, JobRow.sim_backend)
    plans_query, trials_query = select(TestPlanRow), select(PhysicalTrialRow)
    if job_id is not None:
        jobs_query = jobs_query.where(JobRow.id == job_id)
        plans_query = plans_query.where(TestPlanRow.job_id == job_id)
        trials_query = trials_query.where(PhysicalTrialRow.job_id == job_id)
    with db.session() as s:
        jobs = {row.id: (experiment_id(row.experiment_number), row.sim_backend) for row in s.execute(jobs_query)}
        if job_id is not None and job_id not in jobs:
            raise JobNotFoundError(job_id)
        planned = {(plan.job_id, row.trial_id): row for plan in s.scalars(plans_query) for row in plan.rows}
        trials = [PhysicalTrial.model_validate(row) for row in s.scalars(trials_query)]
    trials.sort(key=lambda t: (jobs.get(t.job_id, ("", ""))[0], trial_number(t.trial_id) or 0, t.trial_id))
    out = []
    for trial in trials:
        prediction = planned.get((trial.job_id, trial.trial_id))
        exp, backend = jobs.get(trial.job_id, (None, None))
        data = trial.model_dump(exclude={"id", "created"})
        out.append(
            {name: data.get(name) for name in EXPORT_COLUMNS}
            | {
                "experiment_id": exp,
                "predicted": prediction.predicted if prediction else None,
                "predicted_in_tolerance": prediction.predicted_in_tolerance if prediction else None,
                "sim_backend": backend,
            }
        )
    return out


def export_csv(db: DatabaseClient, job_id: str | None = None) -> bytes:
    """export_rows() as CSV: booleans as true / false, history as JSON text."""
    rows = [
        {name: json.dumps(value) if name == "history" or isinstance(value, bool) else value for name, value in row.items()}
        for row in export_rows(db, job_id)
    ]
    return spreadsheets.write_csv(EXPORT_COLUMNS, rows)


def export_file_name(db: DatabaseClient, job_id: str | None, suffix: str) -> str:
    """<slug(name)>_<EXP-id>_physical.<suffix> for one job; physical.<suffix> for every job."""
    if job_id is None:
        return f"physical.{suffix}"
    return f"{test_plans.export_stem(printed_fingers.load_job(db, job_id))}_physical.{suffix}"


def now_iso() -> str:
    """The local time with its UTC offset, to the second: what a blank timestamp is filled with."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _badge(planned: int, logged: int, logged_planned: int) -> PhysicalBadge:
    if logged == 0:
        return "none"
    return "validated" if planned > 0 and logged_planned >= planned else "in_progress"


def _scope(db: DatabaseClient, job: Job, plan_id: int | None, designs: list[str]) -> _Scope:
    with db.session() as s:
        plans = [TestPlan.model_validate(row) for row in s.scalars(select(TestPlanRow).where(TestPlanRow.job_id == job.id))]
        extras = {
            row.trial_id: PhysicalTrial.model_validate(row)
            for row in s.scalars(select(PhysicalTrialRow).where(PhysicalTrialRow.job_id == job.id, PhysicalTrialRow.kind == "extra"))
        }
    planned = {row.trial_id: (plan.id, row) for plan in plans for row in plan.rows}
    return _Scope(job, plan_id, planned, extras, designs, printed_fingers.trial_finger_ids(db, job))


def _check(row: int, values: Mapping[str, Any], scope: _Scope) -> _Entry | RowError | None:
    """One row (or quick log) checked against the job's plans: an entry to log, or every reason it can't be. None for a
    row without a trial ID that has nothing to log either (only app-filled cells such as experiment_id)."""
    problems: list[str] = []
    exp = _text(values.get("experiment_id"))
    if exp is not None and exp != scope.job.experiment_id:
        problems.append(f"experiment_id {exp} isn't this experiment ({scope.job.experiment_id})")
    design = _text(values.get("design_label"))
    x, y, yaw = (_number(values, name, problems) for name in ("offset_x_mm", "offset_y_mm", "yaw_deg"))
    repeat = _count(values, "repeat", problems)
    outcome = _outcome(values.get("outcome"), problems)
    in_tolerance = _yes_no(values.get("in_tolerance"), problems)
    timestamp = _timestamp(values.get("timestamp"), problems)
    finger, notes, video_link, operator = (_text(values.get(name)) for name in ("finger_id", "notes", "video_link", "operator"))
    raw_id, planned_finger = _text(values.get("trial_id")), None
    if raw_id is None and all(
        v is None for v in (design, x, y, yaw, outcome, in_tolerance, timestamp, finger, notes, video_link, operator)
    ):
        return None
    if raw_id is not None:
        tid, plan_id, kind, where = _known(raw_id, scope, problems)
        if where is not None:
            problems += _mismatches(where, design, x, y, yaw, repeat)
            design, x, y, yaw, repeat = where.design_label, where.offset_x_mm, where.offset_y_mm, where.yaw_deg, where.repeat
            planned_finger = where.finger_id
    else:
        tid, plan_id, kind = None, scope.plan_id, "extra"
        missing = [
            name for name, value in (("its design", design), ("offset_x_mm", x), ("offset_y_mm", y), ("outcome", outcome)) if value is None
        ]
        if missing:
            problems.append(f"no trial_id: a new row is logged as an extra trial, and needs {', '.join(missing)}")
        if design is not None and design not in scope.designs:
            where_to = "this plan" if scope.plan_id is not None else scope.job.experiment_id
            problems.append(f"design {design} isn't in {where_to} ({', '.join(scope.designs)})")
    if problems:
        return RowError(row=row, trial_id=tid if raw_id is not None else None, reason="; ".join(problems))
    return _Entry(
        row=row,
        trial_id=tid,
        plan_id=plan_id,
        kind=kind,
        design_label=design,
        finger_id=finger or planned_finger or scope.finger_ids.get(design),
        finger_given=finger is not None,
        offset_x_mm=x,
        offset_y_mm=y,
        yaw_deg=0.0 if yaw is None else yaw,
        repeat=1 if repeat is None else repeat,
        outcome=outcome,
        in_tolerance=in_tolerance,
        notes=notes or "",
        video_link=video_link,
        operator=operator,
        timestamp=timestamp,
    )


def _known(raw_id: str, scope: _Scope, problems: list[str]) -> tuple[str, int | None, str, PlannedTrial | PhysicalTrial | None]:
    """(trial ID, its plan, its kind, the planned or extra trial it names), or None for the last if it names none."""
    number = trial_number(raw_id)
    if number is None:
        problems.append(f"trial_id {raw_id} isn't a trial ID (T0001, T0002, ...)")
        return raw_id, None, "extra", None
    tid = trial_id(number)
    if tid in scope.planned:
        plan_id, where = scope.planned[tid]
        kind = where.kind
    elif tid in scope.extras:
        where = scope.extras[tid]
        plan_id, kind = where.plan_id, "extra"
    else:
        where_to = f"test plan {scope.plan_id}" if scope.plan_id is not None else f"any of {scope.job.experiment_id}'s test plans"
        problems.append(f"unknown trial_id {tid}: it isn't in {where_to}")
        return tid, None, "extra", None
    if scope.plan_id is not None and plan_id != scope.plan_id:
        problems.append(
            f"{tid} is in test plan {plan_id}, not this one ({scope.plan_id})"
            if plan_id
            else f"{tid} is an extra trial logged outside any plan"
        )
        return tid, plan_id, kind, None
    return tid, plan_id, kind, where


def _mismatches(
    where: PlannedTrial | PhysicalTrial, design: str | None, x: float | None, y: float | None, yaw: float | None, repeat: int | None
) -> list[str]:
    """Filled-in cells that disagree with the trial they name (blank ones are fine)."""
    out = []
    if design is not None and design != where.design_label:
        out.append(f"design {design} isn't {where.trial_id}'s ({where.design_label})")
    for name, value, planned in (
        ("offset_x_mm", x, where.offset_x_mm),
        ("offset_y_mm", y, where.offset_y_mm),
        ("yaw_deg", yaw, where.yaw_deg),
    ):
        if value is not None and abs(value - planned) > OFFSET_MATCH_MM:
            out.append(f"{name} {value:g} isn't {where.trial_id}'s ({planned:g})")
    if repeat is not None and repeat != where.repeat:
        out.append(f"repeat {repeat} isn't {where.trial_id}'s ({where.repeat})")
    if out:
        out[-1] += "; to log a different offset, add it as a new row with trial_id blank"
    return out


def _apply(db: DatabaseClient, scope: _Scope, entries: list[_Entry], *, match_extras: bool) -> list[tuple[str, PhysicalTrial]]:
    """Log the entries in one unit of work: (status, the trial) for each with an outcome, status "logged", "unchanged" or
    "extra" (a new extra trial). match_extras: a blank-ID entry identical to an extra already logged from this plan is
    that extra (an upload of the same sheet again), not a new one."""
    stamp = now_iso()
    touched = []
    with db.session() as s:
        # The job's whole log (a few thousand rows at most), rather than an IN list as long as the upload.
        logged = list(s.scalars(select(PhysicalTrialRow).where(PhysicalTrialRow.job_id == scope.job.id).order_by(PhysicalTrialRow.id)))
        existing = {row.trial_id: row for row in logged}
        unmatched = [row for row in logged if match_extras and row.kind == "extra" and row.plan_id == scope.plan_id]
        next_number = None
        for entry in entries:
            if entry.outcome is None:
                continue
            if entry.trial_id is not None:
                row = existing.get(entry.trial_id)
                if row is None:
                    row = _new_row(scope.job.id, entry, entry.trial_id, stamp)
                    s.add(row)
                    status = "logged"
                elif _same(row, entry):
                    status = "unchanged"
                else:
                    _overwrite(row, entry, stamp)
                    status = "logged"
            else:
                row = next((extra for extra in unmatched if _same_extra(extra, entry)), None)
                if row is not None:
                    unmatched.remove(row)
                    status = "unchanged"
                else:
                    next_number = next_number or test_plans.next_trial_number(s, scope.job.id)
                    row = _new_row(scope.job.id, entry, trial_id(next_number), stamp)
                    next_number += 1
                    s.add(row)
                    status = "extra"
            touched.append((status, row))
        s.flush()
        out = [(status, PhysicalTrial.model_validate(row)) for status, row in touched]
    return out


def _new_row(job_id: str, entry: _Entry, tid: str, stamp: str) -> PhysicalTrialRow:
    return PhysicalTrialRow(
        job_id=job_id,
        plan_id=entry.plan_id,
        trial_id=tid,
        design_label=entry.design_label,
        finger_id=entry.finger_id,
        kind=entry.kind,
        offset_x_mm=entry.offset_x_mm,
        offset_y_mm=entry.offset_y_mm,
        yaw_deg=entry.yaw_deg,
        repeat=entry.repeat,
        outcome=entry.outcome,
        in_tolerance=entry.in_tolerance,
        notes=entry.notes,
        video_link=entry.video_link,
        operator=entry.operator,
        timestamp=entry.timestamp or stamp,
        history=[],
    )


def _same(row: PhysicalTrialRow, entry: _Entry) -> bool:
    """Whether logging the entry would change nothing: the operator's values match, and so do the finger and timestamp
    where they were typed in (a blank one means "as before")."""
    return (
        (row.outcome, row.in_tolerance, row.notes or "", row.video_link, row.operator)
        == (entry.outcome, entry.in_tolerance, entry.notes, entry.video_link, entry.operator)
        and (not entry.finger_given or row.finger_id == entry.finger_id)
        and (entry.timestamp is None or _same_time(row.timestamp, entry.timestamp))
    )


def _same_extra(row: PhysicalTrialRow, entry: _Entry) -> bool:
    return (
        row.design_label == entry.design_label
        and offset_key(row.offset_x_mm, row.offset_y_mm, row.yaw_deg) == offset_key(entry.offset_x_mm, entry.offset_y_mm, entry.yaw_deg)
        and row.repeat == entry.repeat
        and _same(row, entry)
    )


def _overwrite(row: PhysicalTrialRow, entry: _Entry, stamp: str) -> None:
    """Log the entry over the row, keeping the old values in its history."""
    row.history = [*row.history, {name: getattr(row, name) for name in LOGGED_FIELDS} | {"replaced": stamp}]
    row.outcome, row.in_tolerance, row.notes = entry.outcome, entry.in_tolerance, entry.notes
    row.video_link, row.operator = entry.video_link, entry.operator
    row.finger_id = entry.finger_id if entry.finger_given else row.finger_id or entry.finger_id
    row.timestamp = entry.timestamp or stamp


def _design_validation(
    job: Job, label: str, rows: list[PlannedTrial], trials: dict[str, PhysicalTrial], *, finger_ids: list[str], extras: int
) -> tuple[DesignValidation, list[MismatchPoint], list[CurvePoint]]:
    kind = job.spec.task.kind
    results = [(row, trials.get(row.trial_id)) for row in rows]
    scored = [(row, _success(trial, kind)) for row, trial in results]
    counted = [(row, ok) for row, ok in scored if ok is not None]
    n, k = len(counted), sum(ok for _, ok in counted)
    low, high = wilson_interval(k, n) if n else (None, None)

    groups: dict[tuple[str, tuple[float, float, float]], list[tuple[PlannedTrial, bool | None]]] = {}
    for row, ok in scored:
        groups.setdefault((row.kind, row.offset), []).append((row, ok))
    points = [_point(label, kind_, offset, members) for (kind_, offset), members in groups.items()]
    pointwise = [p for p in points if p.kind == "pointwise"]
    compared = [p for p in pointwise if p.status != "pending"]
    agreed = sum(1 for p in compared if p.status == "agreed")
    if compared:
        summary = f"sim matched reality on {agreed} of {len(compared)} offsets"
        if len(compared) < len(pointwise):
            summary += f" ({len(pointwise) - len(compared)} not compared yet)"
    else:
        summary = "no point-wise offsets tested yet" if pointwise else "no point-wise offsets planned"

    design = DesignValidation(
        design_label=label,
        finger_ids=finger_ids,
        planned=len(rows),
        logged=sum(1 for _, trial in results if trial is not None),
        skipped=sum(1 for _, trial in results if trial is not None and trial.outcome == "skipped"),
        incomplete=sum(1 for _, trial in results if trial is not None and trial.outcome == "held" and _success(trial, kind) is None),
        extras=extras,
        n=n,
        predicted_success=_rate([row.predicted for row, _ in counted]),
        measured_success=k / n if n else None,
        wilson_low=low,
        wilson_high=high,
        offsets=len(pointwise),
        offsets_compared=len(compared),
        offsets_agreed=agreed,
        summary=summary,
    )
    random = [(row, ok) for row, ok in counted if row.kind == "random"]
    curve = []
    if random:
        m = sum(ok for _, ok in random)
        r_low, r_high = wilson_interval(m, len(random))
        curve.append(
            CurvePoint(
                design_label=label,
                sigma_mm=job.spec.error.sigma_mm,
                measured_success=m / len(random),
                wilson_low=r_low,
                wilson_high=r_high,
                n=len(random),
                predicted_success=_rate([row.predicted for row, _ in random]),
            )
        )
    return design, points, curve


def _point(label: str, kind: str, offset: tuple[float, float, float], members: list[tuple[PlannedTrial, bool | None]]) -> MismatchPoint:
    """One planned offset of one design: the sim's prediction against the majority of the robot's counted trials."""
    predicted = _majority([row.predicted for row, _ in members if row.predicted is not None])
    measured = [ok for _, ok in members if ok is not None]
    majority = _majority(measured)
    status: MismatchStatus
    if not measured or predicted is None:
        status = "pending"
    elif majority is None:
        status = "mixed"
    elif majority == predicted:
        status = "agreed"
    else:
        status = "sim_only" if predicted else "real_only"
    x, y, yaw = offset
    return MismatchPoint(
        design_label=label,
        kind=kind,
        offset_x_mm=x,
        offset_y_mm=y,
        yaw_deg=yaw,
        predicted=predicted,
        measured_rate=sum(measured) / len(measured) if measured else None,
        repeats=len(measured),
        status=status,
    )


def _success(trial: PhysicalTrial | None, kind: TaskKind) -> bool | None:
    """The trial's success at the task, or None when it doesn't count: not logged, skipped, or held on place / insert
    with in_tolerance blank."""
    if trial is None or trial.outcome == "skipped":
        return None
    if trial.outcome == "missed":
        return False
    return True if kind == "drop" else trial.in_tolerance


def _majority(values: list[bool]) -> bool | None:
    """True or False if more than half agree; None for a tie or nothing."""
    yes = sum(values)
    return None if 2 * yes == len(values) else 2 * yes > len(values)


def _rate(values: list[bool | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))  # an operator ID typed as a number
    return str(value).strip() or None


def _number(values: Mapping[str, Any], name: str, problems: list[str]) -> float | None:
    value = values.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        problems.append(f"{name} {value!r} isn't a number")
        return None
    if not math.isfinite(number):
        problems.append(f"{name} {value!r} isn't a number")
        return None
    return number


def _count(values: Mapping[str, Any], name: str, problems: list[str]) -> int | None:
    number = _number(values, name, problems)
    if number is None:
        return None
    if not number.is_integer() or number < 1:
        problems.append(f"{name} {values.get(name)!r} isn't a whole number from 1 up")
        return None
    return int(number)


def _outcome(value: Any, problems: list[str]) -> str | None:
    text = _text(value)
    if text is None:
        return None
    if text.lower() not in TRIAL_OUTCOMES:
        problems.append(f"outcome {text!r} isn't held, missed or skipped")
        return None
    return text.lower()


def _yes_no(value: Any, problems: list[str]) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    text = _text(value)
    if text is None:
        return None
    if text.lower() in ("yes", "y", "true", "1"):
        return True
    if text.lower() in ("no", "n", "false", "0"):
        return False
    problems.append(f"in_tolerance {text!r} isn't yes or no (or blank)")
    return None


def _timestamp(value: Any, problems: list[str]) -> str | None:
    """ISO text (seconds), from ISO or Excel's month/day/year text; None if blank."""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text).isoformat(timespec="seconds")
    except ValueError:
        pass
    for pattern in TIME_FORMATS:
        try:
            return datetime.strptime(text, pattern).isoformat(timespec="seconds")
        except ValueError:
            continue
    problems.append(f"timestamp {text!r} isn't a date and time (e.g. 2026-10-19 14:30)")
    return None


def _same_time(a: str | None, b: str | None) -> bool:
    """Equal timestamps, ignoring a UTC offset one of them lost (Excel drops them)."""
    if a is None or b is None:
        return a == b
    try:
        return datetime.fromisoformat(a).replace(tzinfo=None) == datetime.fromisoformat(b).replace(tzinfo=None)
    except ValueError:
        return a == b
