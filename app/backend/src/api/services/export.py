"""Exports of simulated results: trials.jsonl, every design the sim tried with its raw outcomes on its grid: the training
data for surrogate models and anyone re-analysing a run. Physical-trial exports belong to the results tracker
(services/physical_trials.py).

Each row carries what it needs to be read on its own: the job's badge (mock rows are never predictions), the part as the
gripper met it, the task and error model it was scored for, and its grid's definition (OffsetGrid.points() regenerates
the offsets its held / in_hand lists are aligned with).

A job covering several resting poses (api/models/job_pose.py) keeps part, held, in_hand and held_after_transport the
primary pose's, and adds `poses` (each pose's key, label, likelihood, weight, grasp and part, in order) and
`pose_outcomes` (every other pose's raw outcomes, in that order). success_rate is then weighted over the poses.
"""

from typing import Any

from sqlalchemy import select

from api.clients.database import DatabaseClient
from api.db.tables import JobRow, ResultRow, TrialRow
from api.models.job import Job, Trial
from api.services.jobs import get_job


def trial_rows(db: DatabaseClient, job_id: str | None = None) -> list[dict[str, Any]]:
    """One row per trial (a design on the search or final grid), for one job or every job, oldest job first. Generation
    jobs only: an evaluation job's trials are library fingers, not designs (none for an evaluation job's id). Raises
    JobNotFoundError for an unknown job_id."""
    if job_id is not None:
        get_job(db, job_id)
    jobs_query = select(JobRow).where(JobRow.kind == "generation").order_by(JobRow.experiment_number)
    trials_query = select(TrialRow).order_by(TrialRow.job_id, TrialRow.number)
    results_query = select(ResultRow.job_id, ResultRow.trial_number)
    if job_id is not None:
        jobs_query = jobs_query.where(JobRow.id == job_id)
        trials_query = trials_query.where(TrialRow.job_id == job_id)
        results_query = results_query.where(ResultRow.job_id == job_id)
    with db.session() as s:
        found = [Job.model_validate(row) for row in s.scalars(jobs_query)]
        trials: dict[str, list[tuple[Trial, float]]] = {}
        for row in s.scalars(trials_query):
            trials.setdefault(row.job_id, []).append((Trial.model_validate(row), row.duration))
        chosen = set(s.execute(results_query).all())
    rows = []
    for job in found:
        part, task, error = job.part.model_dump(mode="json"), job.spec.task.model_dump(mode="json"), job.spec.error.model_dump(mode="json")
        grids = {"search": job.plan.grid.model_dump(mode="json"), "final": job.plan.final_grid.model_dump(mode="json")}
        several = len(job.poses) > 1
        poses = [pose.model_dump(mode="json", exclude={"resting"}) for pose in job.poses] if several else None
        for trial, duration in trials.get(job.id, []):
            extra = {}
            if several:
                extra = {"poses": poses, "pose_outcomes": [out.model_dump(mode="json") for out in trial.pose_outcomes or []]}
            rows.append(
                {
                    "job_id": job.id,
                    "experiment_id": job.experiment_id,
                    "name": job.name,
                    "sim_backend": job.sim_backend,
                    "part_id": job.part_id,
                    "part": part,
                    "task": task,
                    "error": error,
                    "number": trial.number,
                    "search": trial.search,
                    "grid": trial.grid,
                    "round": trial.round,
                    "kind": trial.kind,
                    "label": trial.label,
                    "params": None if trial.params is None else trial.params.model_dump(mode="json"),
                    "success_rate": trial.success_rate,
                    "capture_radius_mm": trial.capture_radius_mm,
                    "n_grasps": trial.n_grasps,
                    "held": trial.held,
                    "in_hand": [None if pose is None else list(pose) for pose in trial.in_hand],
                    "held_after_transport": trial.held_after_transport,
                    "grid_definition": grids[trial.grid],
                    "duration_s": duration,  # its share of its round's sim time; 0 for a design that wasn't simulated
                    "chosen_best": (job.id, trial.number) in chosen,  # D1's final-grid trial
                    **extra,
                }
            )
    return rows
