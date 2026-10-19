"""A design job and what it produces: LLM suggestions, simulated trials and the final result."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from api.models.part import Part
from api.models.physical_trial import PhysicalTrial
from api.models.review import Review

JobStatus = Literal["queued", "running", "done", "failed", "cancelled", "interrupted"]
FINISHED_STATUSES = ("done", "failed", "cancelled", "interrupted")
RESUMABLE_STATUSES = ("interrupted", "cancelled", "failed")


class JobConfig(BaseModel):
    """How a job searches: the camera-error model, the budget and the parallelism."""

    sigma_mm: float = 3  # camera position error, 1 sigma
    sigma_deg: float = 8  # camera yaw error, 1 sigma
    n_suggestions: int = 6
    budget: int = 60  # simulated designs
    n_grasps: int = 40  # grasps per design
    workers: int = 0  # 0: all CPUs but one
    seed: int = 0
    patience: int = 25  # stop after this many trials without improvement
    prune: bool = True


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: str
    created: float
    status: JobStatus
    part_name: str
    part_path: str | None = None
    part: Part
    task: str
    config: JobConfig
    n_done: int = 0
    n_total: int = 0
    stage: str | None = None  # llm, optimize, finalize
    best_value: float | None = None
    best_trial: int | None = None
    error: str | None = None
    cancel_requested: int = 0
    pid: int | None = None
    finished: float | None = None


class Suggestion(BaseModel):
    """A starting design proposed by the LLM. trial_number links it to the trial that evaluated it."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    idx: int
    template: str
    params: dict[str, float]
    rationale: str | None
    source: str
    model: str | None
    trial_number: int | None


class Trial(BaseModel):
    """One simulated design. Pruned trials stopped early and have a less reliable success rate."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    number: int
    template: str
    params: dict[str, float]
    success_rate: float
    n_grasps: int
    pruned: int
    suggestion_id: int | None


class JobResult(BaseModel):
    """The winning design, re-validated on fresh perturbations, with its printable CAD file."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    job_id: str
    trial_number: int
    template: str
    params: dict[str, float]
    grasp_pose: dict[str, Any]
    predicted_success: float
    ci_low: float
    ci_high: float
    scad_path: str
    created: float


class JobDetail(BaseModel):
    job: Job
    suggestions: list[Suggestion]
    trials: list[Trial]
    result: JobResult | None
    meta: dict[str, Any] | None  # run metadata for reproducibility: versions, hardware, backends
    review: Review | None
    physical: list[PhysicalTrial]
