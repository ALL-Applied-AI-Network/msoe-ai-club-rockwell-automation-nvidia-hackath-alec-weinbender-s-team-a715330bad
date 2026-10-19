"""Training-data export for the stretch goal: one row per simulated design, LLM suggestion or physical trial."""

from sqlalchemy import and_, select

from api.clients.database import DatabaseClient
from api.db.tables import JobRow, ResultRow, SuggestionRow, TrialRow
from api.models.part import Part
from api.services import physical_trials


def part_key(part: Part) -> str:
    """Identifies the part. Split train/test by this, not by row, so the same part never lands on both sides."""
    return f"{part.shape}-{part.diameter_mm:g}x{part.length_mm:g}"


def physical_rows(db: DatabaseClient) -> list[dict]:
    return [trial.model_dump() for trial in physical_trials.list_trials(db)]


def trial_rows(db: DatabaseClient) -> list[dict]:
    """One row per simulated design: features plus the success-rate label, with context to train a surrogate."""
    query = (
        select(TrialRow, JobRow, ResultRow.trial_number)
        .join(JobRow, JobRow.id == TrialRow.job_id)
        .outerjoin(ResultRow, ResultRow.job_id == TrialRow.job_id)
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
                "template": t.template,
                "params": t.params,
                "success_rate": t.success_rate,
                "n_grasps": t.n_grasps,
                "pruned": bool(t.pruned),
                "from_llm": t.suggestion_id is not None,
                "chosen_best": chosen == t.number,
            }
            for t, job, chosen in s.execute(query)
        ]


def suggestion_rows(db: DatabaseClient) -> list[dict]:
    """Every LLM proposal with its simulated outcome and the job's best: labels for a 'reject bad suggestion' classifier."""
    query = (
        select(SuggestionRow, JobRow, TrialRow.success_rate, TrialRow.n_grasps, ResultRow.predicted_success)
        .join(JobRow, JobRow.id == SuggestionRow.job_id)
        .outerjoin(TrialRow, and_(TrialRow.job_id == SuggestionRow.job_id, TrialRow.number == SuggestionRow.trial_number))
        .outerjoin(ResultRow, ResultRow.job_id == SuggestionRow.job_id)
        .order_by(SuggestionRow.id)
    )
    with db.session() as s:
        return [
            {
                "job_id": sug.job_id,
                "part_key": part_key(job.part),
                "part": job.part.model_dump(),
                "task": job.task,
                "sigma_mm": job.config.sigma_mm,
                "sigma_deg": job.config.sigma_deg,
                "template": sug.template,
                "params": sug.params,
                "rationale": sug.rationale,
                "source": sug.source,
                "model": sug.model,
                "success_rate": success_rate,
                "n_grasps": n_grasps,
                "job_best": best,
            }
            for sug, job, success_rate, n_grasps, best in s.execute(query)
        ]
