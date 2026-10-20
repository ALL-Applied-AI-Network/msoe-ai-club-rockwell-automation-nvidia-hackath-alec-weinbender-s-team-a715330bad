"""Training data export for the stretch goal: one row per simulated design or physical trial."""

from sqlalchemy import select

from api.clients.database import DatabaseClient
from api.db.tables import JobRow, ResultRow, RunMetaRow, TrialRow
from api.models.part import Part
from api.services import physical_trials


def part_key(part: Part) -> str:
    """Identifies the part. Split train/test by this, not by row, so the same part never lands on both sides."""
    if part.shape == "box":
        return f"box-{part.width_mm:g}x{part.depth_mm:g}x{part.height_mm:g}"
    return f"cylinder-{part.diameter_mm:g}x{part.length_mm:g}-{'upright' if part.upright else 'lying'}"


def physical_rows(db: DatabaseClient) -> list[dict]:
    return [trial.model_dump() for trial in physical_trials.list_trials(db)]


def trial_rows(db: DatabaseClient) -> list[dict]:
    """One row per simulated design: its parameters, its score, and the raw result at every grid point (with the grid,
    so a surrogate can be trained on any error level)."""
    query = (
        select(TrialRow, JobRow, ResultRow.trial_number, RunMetaRow.meta)
        .join(JobRow, JobRow.id == TrialRow.job_id)
        .outerjoin(ResultRow, ResultRow.job_id == TrialRow.job_id)
        .outerjoin(RunMetaRow, RunMetaRow.job_id == TrialRow.job_id)
        .order_by(TrialRow.id)
    )
    with db.session() as s:
        return [
            {
                "job_id": t.job_id,
                "part_key": part_key(job.part),
                "part": job.part.model_dump(),
                "task": job.task,
                "sigma_mm": job.config.sigma_mm,
                "sigma_deg": job.config.sigma_deg,
                "round": t.round,
                "kind": t.kind,
                "params": t.params,
                "success_rate": t.success_rate,
                "capture_radius_mm": t.capture_radius_mm,
                "held": t.held,
                "grid": (meta or {}).get("grid"),
                "chosen_best": chosen == t.number,
            }
            for t, job, chosen, meta in s.execute(query)
        ]
