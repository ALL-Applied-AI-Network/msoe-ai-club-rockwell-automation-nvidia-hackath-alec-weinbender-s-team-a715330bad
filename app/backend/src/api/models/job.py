"""A job (an experiment): a run the worker does on the sim, and what it produces. There are two kinds:

- generation: the optimizer designs new fingers for a part (simulated trials round by round, then the final result);
- evaluation: the fingers already in the library are tried on a part and ranked (api/models/evaluation.py).

Both kinds share the job's lifecycle: queued, run by a detached worker, cancelled, resumed, with live progress. A job
has a name the user can change and an experiment ID that never changes (EXP-0042): printed fingers and logged physical
trials refer to the ID.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Tag, computed_field, model_validator

from api.models.design import DesignKind
from api.models.error_model import ErrorModel
from api.models.evaluation import EvaluationPlan, EvaluationSpec
from api.models.export_check import ExportCheck
from api.models.family import FamilyParams
from api.models.job_pose import JobPose
from api.models.job_spec import JobSpec, SimBackend
from api.models.outcome import InHand, Landing, Outcomes
from api.models.part import Part
from api.models.search_plan import JobPlan

JobKind = Literal["generation", "evaluation"]
JobStatus = Literal["queued", "running", "finalizing", "done", "failed", "cancelled", "interrupted"]


def kind_of(value: Any) -> str:
    """A spec's or plan's kind: its "kind", or generation for one stored before evaluation jobs existed (it has none)."""
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return kind or "generation"


AnySpec = Annotated[Annotated[JobSpec, Tag("generation")] | Annotated[EvaluationSpec, Tag("evaluation")], Discriminator(kind_of)]
AnyPlan = Annotated[Annotated[JobPlan, Tag("generation")] | Annotated[EvaluationPlan, Tag("evaluation")], Discriminator(kind_of)]
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
    kind: JobKind = "generation"
    status: JobStatus
    part_id: str
    cell_profile_id: int
    sim_backend: SimBackend
    spec: AnySpec  # a JobSpec for a generation job, an EvaluationSpec for an evaluation job
    part: Part  # as the gripper meets it (resting pose and grasp axis applied) in the primary pose, snapshotted at creation
    plan: AnyPlan
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
    batch_id: str | None = None  # evaluation jobs created together, one per part

    @model_validator(mode="after")
    def _consistent(self) -> "Job":
        if self.spec.kind != self.kind or self.plan.kind != self.kind:
            raise ValueError(f"a {self.kind} job needs a {self.kind} spec and plan")
        if self.spec.error is None:  # only a row written by hand: create_job always fills it in from the cell profile
            self.spec = self.spec.with_error(ErrorModel())
        return self

    @computed_field
    @property
    def experiment_id(self) -> str:
        return experiment_id(self.experiment_number)

    @property
    def poses(self) -> list[JobPose]:
        """A generation job's resting poses, primary first (api/models/job_pose.py). A job from before jobs covered
        poses has one: its spec's grasp on its part. An evaluation job's poses are in its plan (EvaluationPlan.poses)."""
        if self.kind != "generation":
            raise ValueError("an evaluation job's poses are in its plan")
        return self.plan.poses or [JobPose(key="p0", grasp=self.spec.grasp, part=self.part)]


class Trial(BaseModel):
    """One design, tried at every point of a grid: the search grid while optimizing, the dense final grid at the end.
    success_rate and capture_radius_mm are for the job's own error model and task; the raw outcomes re-score to any
    other. held, in_hand and held_after_transport are the primary pose's; pose_outcomes holds every other pose's, in the
    job's pose order (None for a job covering one pose). success_rate is weighted over the poses, capture_radius_mm the
    smallest, and n_grasps counts every pose's."""

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
    landing: list[Landing | None] | None = None  # None: not measured (a sim server from before 2026-10-26)
    pose_outcomes: list[Outcomes] | None = None

    def outcomes(self) -> Outcomes:
        """The primary pose's outcomes."""
        return Outcomes(held=self.held, in_hand=self.in_hand, held_after_transport=self.held_after_transport, landing=self.landing)

    def outcomes_by_pose(self) -> list[Outcomes]:
        """Every pose's outcomes, in the job's pose order."""
        return [self.outcomes(), *(self.pose_outcomes or [])]


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
