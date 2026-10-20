"""An experiment's print selection and its printed fingers (the results tracker; docs/notes/input-flow-backend-plan.md,
4.8).

After the final test the user picks which designs to print, by their final-table labels (D1, D2, ...). The baselines are
always tested on the robot too: STOCK on the aluminium fingers already fitted, IMP printed like the chosen designs. Every
finger that comes off the printer is recorded under the ID engraved on it (EXP-0042-D1-L), so a logged trial can name
the fingers it used. The test plans and physical trials services build on the helpers here (the finished job, its
labels and designs).
"""

import logging
import re
from datetime import date

from sqlalchemy import select

from api.clients.database import DatabaseClient
from api.db.tables import JobRow, PrintedFingerRow, TrialRow
from api.models.design import Design
from api.models.job import Job
from api.models.printed_finger import PrintedFinger, PrintSelection, Side, finger_id
from api.services.jobs import JobNotFoundError

logger = logging.getLogger(__name__)

STOCK, IMPRINT = "STOCK", "IMP"
BASELINES = (IMPRINT, STOCK)  # in the order they follow the chosen designs


class JobNotDoneError(RuntimeError):
    """The job hasn't finished its final test, so it has no design labels yet."""


class DesignLabelError(ValueError):
    """A design label the job's final test doesn't have, or one that can't be used here (STOCK can't be printed)."""


class PrintedFingerError(ValueError):
    """A printed finger that can't be recorded as sent (no material)."""


def load_job(db: DatabaseClient, job_id: str) -> Job:
    with db.session() as s:
        row = s.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError(job_id)
        return Job.model_validate(row)


def done_job(db: DatabaseClient, job_id: str) -> Job:
    """The job, if its final test is done (status "done")."""
    job = load_job(db, job_id)
    if job.status != "done":
        raise JobNotDoneError(f"{job.experiment_id} is {job.status}: designs get their labels (D1, D2, ...) when it's done")
    return job


def final_designs(db: DatabaseClient, job_id: str) -> dict[str, Design | None]:
    """Every design of the job's final test by label, D1, D2, ... then IMP and STOCK: what to build each one from. STOCK
    is None, the stock fingers already on the robot (the sim has its own)."""
    query = select(TrialRow.label, TrialRow.kind, TrialRow.params).where(
        TrialRow.job_id == job_id, TrialRow.grid == "final", TrialRow.label.is_not(None)
    )
    with db.session() as s:
        rows = s.execute(query).all()
    designs: dict[str, Design | None] = {}
    for label, kind, params in rows:
        if kind == "stock":
            designs[label] = None
        elif kind == "imprint":
            designs[label] = Design(kind="imprint")
        else:
            designs[label] = Design(kind=kind, params=params)  # validated into the family's params model
    return {label: designs[label] for label in sorted(designs, key=label_order)}


def label_order(label: str) -> tuple[int, int, str]:
    """D1, D2, ..., D10 by number, then IMP, then STOCK, then anything else."""
    match = re.fullmatch(r"D(\d+)", label)
    if match:
        return 0, int(match.group(1)), label
    return (1, 0, label) if label == IMPRINT else (2, 0, label) if label == STOCK else (3, 0, label)


def tested_designs(job: Job, available: list[str]) -> list[str]:
    """What a test plan covers: the print selection, then IMP and STOCK (those the final test has)."""
    chosen = [label for label in job.print_designs if label in available and label not in BASELINES]
    return chosen + [label for label in BASELINES if label in available]


def get_print_selection(db: DatabaseClient, job_id: str) -> PrintSelection:
    job = done_job(db, job_id)
    return _selection(job, list(final_designs(db, job_id)))


def set_print_selection(db: DatabaseClient, job_id: str, designs: list[str]) -> PrintSelection:
    """Choose the designs to print, by final-table label. STOCK and IMP are dropped from the list if sent, since they're
    always tested; repeats are dropped too. Test plans already made keep their own designs."""
    job = done_job(db, job_id)
    available = list(final_designs(db, job_id))
    labels = [label.strip() for label in designs]
    unknown = [label for label in labels if label not in available]
    if unknown:
        raise DesignLabelError(f"{job.experiment_id} has no design {', '.join(unknown)}; its final test has {', '.join(available)}")
    chosen = list(dict.fromkeys(label for label in labels if label not in BASELINES))
    with db.session() as s:
        s.get(JobRow, job_id).print_designs = chosen
    logger.info("Job %s: print selection %s", job_id, ", ".join(chosen) or "(baselines only)")
    return _selection(job.model_copy(update={"print_designs": chosen}), available)


def add_printed_finger(
    db: DatabaseClient,
    job_id: str,
    *,
    design_label: str,
    side: Side = "pair",
    material: str,
    print_date: date | None = None,
    notes: str = "",
) -> PrintedFinger:
    """Record a printed finger (or pair) of one of the job's designs. Its ID is the one engraved on it."""
    job = done_job(db, job_id)
    available = list(final_designs(db, job_id))
    label = design_label.strip()
    if label not in available:
        raise DesignLabelError(f"{job.experiment_id} has no design {label}; its final test has {', '.join(available)}")
    if label == STOCK:
        raise DesignLabelError("STOCK is the aluminium fingers already on the robot: nothing to print")
    if not material.strip():
        raise PrintedFingerError("material is required (it should match the friction the sim assumed)")
    row = PrintedFingerRow(
        job_id=job_id,
        finger_id=finger_id(job.experiment_id, label, side),
        design_label=label,
        side=side,
        material=material.strip(),
        print_date=print_date.isoformat() if print_date else None,
        notes=notes,
    )
    with db.session() as s:
        s.add(row)
        s.flush()
        finger = PrintedFinger.model_validate(row)
    logger.info("Job %s: printed finger %s recorded", job_id, finger.finger_id)
    return finger


def list_printed_fingers(db: DatabaseClient, job_id: str) -> list[PrintedFinger]:
    """The job's printed fingers, in the order they were recorded."""
    load_job(db, job_id)
    query = select(PrintedFingerRow).where(PrintedFingerRow.job_id == job_id).order_by(PrintedFingerRow.id)
    with db.session() as s:
        return [PrintedFinger.model_validate(row) for row in s.scalars(query)]


def trial_finger_ids(db: DatabaseClient, job: Job) -> dict[str, str]:
    """The finger ID a trial of each design is logged with: the pair's (EXP-0042-D1), for every design with at least one
    printed finger. A grasp uses both sides, so the pair is what a trial tested."""
    query = select(PrintedFingerRow.design_label).where(PrintedFingerRow.job_id == job.id).distinct()
    with db.session() as s:
        labels = list(s.scalars(query))
    return {label: finger_id(job.experiment_id, label) for label in labels}


def _selection(job: Job, available: list[str]) -> PrintSelection:
    tested = tested_designs(job, available)
    chosen = [label for label in tested if label not in BASELINES]
    return PrintSelection(designs=chosen, printed=[label for label in tested if label != STOCK], tested=tested, available=available)
