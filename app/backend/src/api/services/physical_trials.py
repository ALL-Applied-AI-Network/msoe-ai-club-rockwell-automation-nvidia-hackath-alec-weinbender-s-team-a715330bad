"""Grasp attempts on the real arm, logged by hand after supervised tests at CSI."""

from sqlalchemy import select

from api.clients.database import DatabaseClient
from api.db.tables import PhysicalTrialRow
from api.models.physical_trial import PhysicalTrial


def add_trial(
    db: DatabaseClient,
    job_id: str,
    *,
    finger: str,
    success: int,
    placement_error_mm: float | None,
    cycle_time_s: float | None,
    recovered: int,
    operator_intervention: int,
    notes: str,
) -> None:
    with db.session() as s:
        s.add(
            PhysicalTrialRow(
                job_id=job_id,
                finger=finger,
                success=success,
                placement_error_mm=placement_error_mm,
                cycle_time_s=cycle_time_s,
                recovered=recovered,
                operator_intervention=operator_intervention,
                notes=notes,
            )
        )


def list_trials(db: DatabaseClient, job_id: str | None = None) -> list[PhysicalTrial]:
    """The job's trials in the order they were logged, or every job's when job_id is None."""
    query = select(PhysicalTrialRow).order_by(PhysicalTrialRow.id)
    if job_id is not None:
        query = query.where(PhysicalTrialRow.job_id == job_id)
    with db.session() as s:
        return [PhysicalTrial.model_validate(row) for row in s.scalars(query)]
