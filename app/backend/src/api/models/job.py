"""An experiment (a design job) and what it produces: simulated trials, round by round, and the final result.

An experiment has a name the user can change and an experiment ID that never changes (EXP-0042): printed fingers and
logged physical trials refer to the ID.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, computed_field

from api.models.design import DesignKind
from api.models.export_check import ExportCheck
from api.models.family import FamilyParams
from api.models.job_spec import JobSpec, SimBackend
from api.models.outcome import InHand, Outcomes
from api.models.part import Part
from api.models.search_plan import JobPlan

JobStatus = Literal["queued", "running", "finalizing", "done", "failed", "cancelled", "interrupted"]
FINISHED_STATUSES = ("done", "failed", "cancelled", "interrupted")
ACTIVE_STATUSES = ("queued", "running", "finalizing")  # a worker has, or is about to have, the job
RESUMABLE_STATUSES = ("interrupted", "cancelled", "failed")
GridKind = Literal["search", "final"]


def experiment_id(number: int) -> str:
    return f"EXP-{number:04d}"


class Job(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: str  # internal key, used in URLs
    experiment_number: int  # fixed for life; experiment_id shows it as EXP-0042
    name: str  # renamable
    created: float
    status: JobStatus
    part_id: str
    cell_profile_id: int
    sim_backend: SimBackend
    spec: JobSpec
    part: Part  # as the gripper meets it (resting pose and grasp axis applied), snapshotted at creation
    plan: JobPlan
    n_done: int = 0  # designs evaluated
    n_total: int = 0  # the plan's designs: every search's budget, the baselines and the final test
    round: int = 0  # rounds done
    n_rounds: int = 0  # rounds planned
    best_value: float | None = None  # best expected success so far (search grid), then the winner's (final grid)
    best_trial: int | None = None
    error: str | None = None  # the traceback, for whoever debugs it
    failure: str | None = None  # one line for the job card, e.g. "no grasp axis fits the 12 mm stroke"
    failed_step: int | None = None  # the input step that fixes it, for the card's link back
    cancel_requested: int = 0
    pid: int | None = None  # of the worker process running the job
    finished: float | None = None
    duplicated_from: str | None = None
    print_designs: list[str] = []  # design labels marked "print this" (stock and imprint are always tested too)

    @computed_field
    @property
    def experiment_id(self) -> str:
        return experiment_id(self.experiment_number)


class Trial(BaseModel):
    """One design, tried at every point of a grid: the search grid while optimizing, the dense final grid at the end.
    success_rate and capture_radius_mm are for the job's own error model and task; the raw outcomes re-score to any
    other."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    number: int
    round: int
    search: str  # the SearchConfig key, or "baseline"
    grid: GridKind
    kind: DesignKind
    label: str | None = None  # final grid only: D1, D2, ... by final score, STOCK, IMP
    params: FamilyParams | None = None
    success_rate: float
    capture_radius_mm: float | None  # every grasp succeeded out to this camera error; None if even the centre failed
    n_grasps: int
    held: list[bool]
    in_hand: list[InHand | None]
    held_after_transport: list[bool] | None = None

    def outcomes(self) -> Outcomes:
        return Outcomes(held=self.held, in_hand=self.in_hand, held_after_transport=self.held_after_transport)


class JobResult(BaseModel):
    """The winning design (D1) after the final test, its grasp pose and its printable CAD."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    job_id: str
    label: str
    trial_number: int  # its final-grid trial
    search: str
    kind: DesignKind
    params: FamilyParams | None = None
    grasp_pose: dict[str, Any]
    predicted_success: float
    capture_radius_mm: float | None
    cad_files: dict[str, str]  # "step" (the pair), "stl_left", "stl_right", "print_sheet" -> path
    checks: list[ExportCheck]  # a failed blocking check stops the downloads
    created: float
