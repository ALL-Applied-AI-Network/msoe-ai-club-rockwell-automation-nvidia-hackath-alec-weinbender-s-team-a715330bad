"""A design job and what it produces: simulated trials, round by round, and the final result."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.models.part import Part
from api.models.physical_trial import PhysicalTrial
from api.models.review import Review

JobStatus = Literal["queued", "running", "done", "failed", "cancelled", "interrupted"]
FINISHED_STATUSES = ("done", "failed", "cancelled", "interrupted")
RESUMABLE_STATUSES = ("interrupted", "cancelled", "failed")


class JobConfig(BaseModel):
    """How a job searches: the camera-error model it scores designs under, the budget and the batch size."""

    sigma_mm: float = Field(3, ge=0)  # camera position error, 1 sigma per axis
    sigma_deg: float = Field(8, ge=0)  # camera yaw error, 1 sigma
    budget: int = Field(128, ge=1)  # designs searched; the stock and imprint baselines come on top
    batch_size: int = Field(16, ge=1)  # designs per round, simulated together
    patience: int = Field(3, ge=1)  # stop after this many rounds without improvement
    seed: int = 0


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
    stage: str | None = None  # optimize, finalize
    best_value: float | None = None
    best_trial: int | None = None
    error: str | None = None
    cancel_requested: int = 0
    pid: int | None = None
    finished: float | None = None


class Trial(BaseModel):
    """One design, tried at every point of the job's offset grid. success_rate is its expected success under the job's
    error model; held is the raw result per grid point, so it can be re-scored at any other error level."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    number: int
    round: int
    kind: str  # search, stock or imprint
    params: dict[str, float]
    success_rate: float
    capture_radius_mm: float | None  # every grasp held out to this camera error; None if even the centre failed
    n_grasps: int
    held: list[bool]


class JobResult(BaseModel):
    """The winning design, re-tested next to the finalists and baselines on a denser grid, with its CAD file. Each
    comparison entry: name, kind, trial_number, success, capture_radius_mm, curve (success at several error levels),
    problems."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    job_id: str
    trial_number: int
    kind: str
    params: dict[str, float]
    grasp_pose: dict[str, Any]
    predicted_success: float
    capture_radius_mm: float | None
    comparison: list[dict[str, Any]]
    scad_path: str
    created: float


class JobDetail(BaseModel):
    job: Job
    trials: list[Trial]
    result: JobResult | None
    meta: dict[str, Any] | None  # run metadata for reproducibility: versions, hardware, backends, grids
    review: Review | None
    physical: list[PhysicalTrial]
