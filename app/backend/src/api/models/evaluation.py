"""Evaluation jobs: every compatible finger in the library tried on one part, and ranked.

A job is a run the worker does on the sim. A generation job (api/models/job_spec.py) designs new fingers with the
optimizer; an evaluation job takes the fingers the factory already has and answers whether any of them grips the part
well enough. The manufacturing engineer decides what "well enough" is; nothing here sets a pass bar.

How it scores (docs/notes/library-evaluation-backend-plan.md, L8 and L9):

- the part is covered in one or more resting poses (by default its likely ones), each weighted by how often it comes to
  rest that way, as a generation job does (api/models/job_pose.py);
- in each pose the app tries the pose's grasp proposals that aren't blocked (up to EVAL_GRASPS), or the one grasp the
  user locked for it;
- every finger is tried at every grasp, on the search grid. One that can't grip a grasp at all (finger.problems) isn't
  simulated there and scores 0 at it, with the reasons kept;
- a finger's score is the sum over poses of the pose's weight times its best grasp's expected success there. That assumes
  the cell knows the part's pose and runs that finger's best grasp for it; the results name that grasp;
- the top EVAL_FINALISTS fingers and the stock fingers are re-tested at their best grasp per pose on the dense grid,
  which takes the optimism out of picking the best of several grasps. The others keep their search-grid score.

Raw outcomes are stored, so any error model or task re-scores without simulating again.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.models.error_model import ErrorModel
from api.models.finger_record import FingerFamily, FingerSource
from api.models.grasp import GraspChoice
from api.models.job_pose import PoseChoice
from api.models.job_spec import MAX_POSES, SimBackend
from api.models.offset_grid import OffsetGrid
from api.models.outcome import InHand, Outcomes
from api.models.part import Part
from api.models.resting_pose import RestingPose
from api.models.search_plan import Blocker, TimeEstimate
from api.models.task import Task

EVAL_GRASPS = 3  # grasp proposals tried per pose, best first
EVAL_FINALISTS = 3  # fingers re-tested on the dense grid, besides the stock fingers
EvaluationStage = Literal["search", "final"]

# Blocker steps of an evaluation job (what its screens fix): 1 part, 2 resting poses, 3 fingers, 4 cell profile, 5 grasps
STEP_PART, STEP_POSES, STEP_FINGERS, STEP_CELL, STEP_GRASPS = 1, 2, 3, 4, 5


class EvaluationPose(BaseModel):
    """One resting pose the evaluation covers, and optionally the one grasp the cell must use in it."""

    pose: Annotated[int, Field(ge=0, strict=True)] | Literal["as_authored"]  # an index into GET /api/parts/{id}/poses
    grasp: GraspChoice | None = None  # locked: only this grasp is tried; None: the pose's grasp proposals


class EvaluationSpec(BaseModel):
    kind: Literal["evaluation"] = "evaluation"
    name: str | None = None  # blank: "<CAD file stem>_<date>"
    part_id: str
    cell_profile_id: int
    poses: list[EvaluationPose] = Field(default_factory=list, max_length=MAX_POSES)  # empty: the part's likely poses
    finger_ids: list[str] | None = None  # None: every unarchived finger for the cell, and its stock fingers
    task: Task = Task()
    error: ErrorModel | None = None  # None: the cell profile's grasp accuracy, copied in when the job is planned

    @model_validator(mode="after")
    def _distinct(self) -> "EvaluationSpec":
        chosen = [p.pose for p in self.poses]
        if len(chosen) != len(set(chosen)):
            raise ValueError("each resting pose can be chosen once")
        if "as_authored" in chosen and len(chosen) > 1:
            raise ValueError('"as in the CAD file" has no likelihood to weigh it by: it can only be the one pose')
        if self.finger_ids is not None and len(self.finger_ids) != len(set(self.finger_ids)):
            raise ValueError("each finger can be chosen once")
        return self

    def with_error(self, default: ErrorModel) -> "EvaluationSpec":
        return self if self.error is not None else self.model_copy(update={"error": default})


class EvaluationGrasp(BaseModel):
    """A grasp the evaluation tries in one pose, and the part as the gripper meets it there."""

    key: str  # "g0", "g1", ... within its pose, best proposal first
    grasp: GraspChoice
    part: Part
    warnings: list[str] = []  # the grasp check's warnings (faces far from parallel, an off-centre grip, ...)


class EvaluationPosePlan(BaseModel):
    key: str  # "p0" is the primary (the likeliest), then "p1", ...
    label: str | None = None
    choice: PoseChoice | None = None
    probability: float | None = None
    weight: float = 1.0
    resting: RestingPose | None = None
    grasps: list[EvaluationGrasp]


class PlannedFinger(BaseModel):
    finger_id: str
    code: str
    name: str
    source: FingerSource
    family: FingerFamily


class Rejection(BaseModel):
    """A finger that can't grip the part at one grasp, and why (finger.problems): it isn't simulated there."""

    finger_id: str
    pose_key: str
    grasp_key: str
    reasons: list[str]


class EvaluationTotals(BaseModel):
    fingers: int
    combinations: int  # finger x pose x grasp
    simulated: int  # the combinations not rejected
    search_offsets: int
    final_offsets: int
    search_grasps: int
    final_grasps: int  # at most: the finalists and stock, at one grasp per pose
    total_grasps: int
    batches: int  # sim requests: one per pose and grasp, then the final test's


class EvaluationPlan(BaseModel):
    kind: Literal["evaluation"] = "evaluation"
    part: Part  # the primary pose's first grasp: what the job card's part preview shows
    poses: list[EvaluationPosePlan]
    fingers: list[PlannedFinger]
    rejections: list[Rejection] = []
    grid: OffsetGrid
    final_grid: OffsetGrid
    finalists: int = EVAL_FINALISTS
    totals: EvaluationTotals
    estimate: TimeEstimate
    warnings: list[str] = []
    blocked: list[str] = []
    blockers: list[Blocker] = []  # steps: STEP_PART ... STEP_GRASPS above
    sim_backend: SimBackend
    grip_force_n: float | None = None  # per jaw, sent with every batch (as a generation job's)

    def rejected(self, finger_id: str, pose_key: str, grasp_key: str) -> list[str] | None:
        """Why this finger can't grip at this grasp, or None if it can."""
        found = next((r for r in self.rejections if (r.finger_id, r.pose_key, r.grasp_key) == (finger_id, pose_key, grasp_key)), None)
        return None if found is None else found.reasons

    def pose(self, key: str) -> EvaluationPosePlan:
        return next(p for p in self.poses if p.key == key)

    def grasp(self, pose_key: str, grasp_key: str) -> EvaluationGrasp:
        return next(g for g in self.pose(pose_key).grasps if g.key == grasp_key)


class EvaluationTrial(BaseModel):
    """One finger at one grasp of one pose, at every point of a grid, with the raw outcomes."""

    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    number: int
    stage: EvaluationStage
    finger_id: str
    pose_key: str
    grasp_key: str
    success_rate: float  # at the job's own error model and task
    capture_radius_mm: float | None
    n_grasps: int
    held: list[bool]
    in_hand: list[InHand | None]
    held_after_transport: list[bool] | None = None
    tip_height_mm: float | None = None  # where the fingertips gripped; None for the stock fingers (the sim's own rule)
    jaw_close_mm: float | None = None
    duration: float  # sim seconds, its share of its batch

    def outcomes(self) -> Outcomes:
        return Outcomes(held=self.held, in_hand=self.in_hand, held_after_transport=self.held_after_transport)


# What the results page shows (services/evaluations.py: ranking)


class FingerGrasp(BaseModel):
    """A finger's best grasp in one pose: where the cell has to grip with it."""

    pose_key: str
    pose_label: str | None
    grasp_key: str
    angle_deg: float
    centre_mm: tuple[float, float]
    span_mm: tuple[float, float] | None
    tip_height_mm: float | None
    jaw_close_mm: float | None
    success: float
    capture_radius_mm: float | None
    stage: EvaluationStage


class GraspScore(BaseModel):
    """A finger at one grasp: its search-grid success, or None and the reasons where it can't grip there."""

    pose_key: str
    grasp_key: str
    success: float | None
    reasons: list[str] = []


class RankedFinger(BaseModel):
    rank: int
    finger_id: str
    code: str
    name: str
    source: FingerSource
    family: FingerFamily
    success: float  # weighted over the poses, at its best grasp in each
    capture_radius_mm: float | None  # the smallest over the poses; None if a pose missed even the centre
    n_grasps: int  # simulated grasps its score is based on
    stage: EvaluationStage  # "final" once re-tested on the dense grid in every pose it grips
    best: list[FingerGrasp]  # per pose it can grip
    grasps: list[GraspScore]
    curve: dict[str, float] = {}  # success at each CURVE_SIGMAS_MM (keys as strings), for the success-vs-accuracy plot
    # Its qualification on this part (real-robot results), if any
    qualification_id: int | None = None
    measured_success: float | None = None
    real_trials: int = 0


class RankingPose(BaseModel):
    key: str
    label: str | None
    weight: float
    grasps: list[EvaluationGrasp]


class EvaluationResults(BaseModel):
    job_id: str
    experiment_id: str
    name: str
    status: str
    sim_backend: SimBackend
    part_id: str
    part_name: str | None
    cell_profile_id: int
    error: ErrorModel
    task: Task
    rescored: bool  # at another error model or task than the job's own
    final: bool  # the final test has run
    poses: list[RankingPose]
    fingers: list[RankedFinger]  # best first
    warnings: list[str] = []
