"""How a job will search, worked out from the user's choices before anything runs (input steps 6-8): one search per
finger family, each with its own method, budget and batch size, plus the totals and time estimate the review screen
shows. Nothing here simulates; the same plan is shown while the user edits ranges and stored on the job when it starts.

Rules (tune once real data exists), by the number of free parameters d in a family:

| d   | method            | initial designs | budget |
| 0   | single evaluation | 1               | 1      |
| 1   | Sobol sweep       | -               | 16     |
| 2   | Sobol sweep       | -               | 32     |
| 3-7 | batch BO          | 2d + 4          | 128    |

A user budget (JobSpec.budget) replaces the Sobol and BO budgets; a single evaluation stays one design.

Rounds: round 0 evaluates every search's n_initial designs (a Sobol sample; the whole sweep for a Sobol search, the one
design for a single evaluation) together with the baselines. Each later round evaluates batch_size designs from every BO
search still running, in one sim request. Batch size q = clamp(round(10 waves x envs / offsets / BO searches), 4, 32),
capped to leave at least 4 learning rounds after round 0. A BO search stops when its best hasn't gained MIN_GAIN over its
last 3d designs (and at least one batch), or its budget is spent. The final test re-runs the top FINALISTS of every
search (the locked design of a single evaluation), the stock and imprint baselines on the dense grid.

A job covering several resting poses (api/models/job_pose.py) searches in the primary pose's space (its ranges and
limits) and simulates every design in every pose: each round is one sim request per pose, so the totals and the time
estimate scale with the number of poses.
"""

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel

from api.models.cell_profile import CellProfile, Gripper
from api.models.error_model import PRESETS
from api.models.family import FamilyChoice, FamilyName, ParamRange
from api.models.finger import build_finger, problems, regrip
from api.models.job_pose import JobPose
from api.models.job_spec import JobSpec, SimBackend
from api.models.offset_grid import OffsetGrid
from api.models.part import Part
from api.models.search_space import ParamSummary, SearchSpace  # ParamSummary lives with the space it describes

BASELINES = ("stock", "imprint")
FINALISTS = 3  # top designs per search re-tested on the dense grid
MIN_GAIN = 0.005  # half a percentage point of expected success
BO_BUDGET = 128
SOBOL_BUDGETS = {1: 16, 2: 32}
WAVES = 10  # grasps per environment per sim request, when sizing batches
BATCH_LIMITS = (4, 32)
MIN_LEARNING_ROUNDS = 4
PATIENCE_PER_PARAM = 3  # designs without gain, per free parameter, before a BO search stops


class FamilySummary(BaseModel):
    family: FamilyName
    label: str
    params: list[ParamSummary]
    free: list[str]
    warnings: list[str] = []


class SearchConfig(BaseModel):
    key: str  # unique within the job; the family's name (a grasp axis would join it, e.g. "vpad@90")
    family: FamilyName
    free: list[str]  # searched, in search order
    locked: dict[str, float]  # fixed values (clipped into the feasible range per design); includes the grip height
    ranges: dict[str, ParamRange]  # user ranges (intersected with the feasible range per design)
    method: Literal["single", "sobol", "bo"]
    n_initial: int  # designs in round 0: before the first GP fit (BO); the whole budget for a Sobol sweep
    budget: int  # designs
    batch_size: int  # designs per round after round 0 (BO); n_initial otherwise
    patience: int  # designs without a MIN_GAIN improvement before the search stops
    clearance_mm: float | None = None  # the part's clearance on the table, which caps the pad (see search_space.py)

    @property
    def choice(self) -> FamilyChoice:
        return FamilyChoice(family=self.family, ranges=self.ranges, locks=self.locked)

    @property
    def rounds(self) -> int:
        """Sim requests this search needs if it runs its whole budget: round 0, then one per batch."""
        if self.method != "bo":
            return 1
        return 1 + math.ceil((self.budget - self.n_initial) / self.batch_size)

    def space(self, part: Part, gripper: Gripper | None = None, others: Sequence[Part] = ()) -> SearchSpace:
        """The search space this search runs in: from_unit() for the optimizer's points, locked_design() for a single
        evaluation. Pass the job's cell profile's gripper, and its other resting poses' parts (others)."""
        return SearchSpace(part, self.choice, gripper, self.clearance_mm, others)

    def stop_reason(self, scores: list[float]) -> Literal["budget", "patience"] | None:
        """Why this search is over, given its designs' scores in the order they were evaluated, or None while it should
        go on: its budget is spent, or (a BO search, after at least one batch) its last `patience` designs gained less
        than MIN_GAIN on its best."""
        if len(scores) >= self.budget:
            return "budget"
        if self.method != "bo" or len(scores) <= self.n_initial:
            return None
        best, stale = None, 0
        for score in scores:
            if best is None or score > best + MIN_GAIN:
                best, stale = score, 0
            else:
                stale += 1
        return "patience" if stale >= self.patience else None


class PlanTotals(BaseModel):
    search_offsets: int  # grid points per design while searching (81, or 243 with yaw)
    final_offsets: int  # on the dense grid (321, or 963)
    search_designs: int  # every search's budget plus the baselines and locked designs
    search_grasps: int
    final_designs: int
    final_grasps: int
    rounds: int  # rounds while searching (the longest search's), plus one for the final test; a sim request per pose each
    total_grasps: int
    poses: int = 1  # resting poses every design is simulated in: the grasps above count each pose


class TimeEstimate(BaseModel):
    seconds: float | None  # None until a throughput is known
    grasps_per_s: float | None
    source: Literal["measured", "configured", "unknown"]  # recent runs on this backend, SIM_GRASPS_PER_S, or neither


class Blocker(BaseModel):
    """Why a job can't run yet, and the input step whose screen fixes it: 1 part (upload, material or mass), 2 resting
    pose, 4 cell profile, 5 grasp axis, 6 finger families."""

    step: int
    reason: str


class JobPlan(BaseModel):
    part: Part  # as the gripper meets it, in the primary pose
    families: list[FamilySummary]
    searches: list[SearchConfig]
    baselines: list[str]  # "stock", "imprint"
    grid: OffsetGrid
    final_grid: OffsetGrid
    totals: PlanTotals
    estimate: TimeEstimate
    warnings: list[str] = []  # shown, but the job can run
    blocked: list[str] = []  # the job can't run until these are fixed
    sim_backend: SimBackend
    # Filled in by the jobs service (services/jobs.py: plan_spec), which knows the part record and the database:
    blockers: list[Blocker] = []  # every blocked reason (the ones above included), with the input step that fixes it
    # Per-jaw force sent with every batch: the lesser of the profile's grip force and the part's max grip force, where
    # either is known (None: the twin's jaw drive). Fixed when the job is created, so later edits don't change a run.
    grip_force_n: float | None = None
    # The resting poses the job covers, primary (the likeliest) first, each with its grasp, weight and posed part. Empty
    # for a job planned before jobs covered poses: it has one, its spec's grasp on `part` (api/models/job.py: Job.poses).
    poses: list[JobPose] = []


def plan_job(
    part: Part,
    spec: JobSpec,
    profile: CellProfile,
    *,
    sim_backend: SimBackend,
    estimate: TimeEstimate,
    clearance_mm: float | None = None,
    poses: list[JobPose] | None = None,
) -> JobPlan:
    """The plan for this part, spec and cell. `estimate` carries the throughput (seconds is filled in here); clearance_mm
    is the part record's clearance on the table, if set. poses: the resting poses the job covers, primary first (its
    part is `part`); None for one, on `part` with the spec's grasp. Collects every problem in warnings / blocked rather
    than raising: a blocked plan still has its totals, so the review screen can show both."""
    gripper = profile.gripper
    poses = poses or [JobPose(key="p0", grasp=spec.grasp, part=part)]
    grid = OffsetGrid.for_parts([pose.part for pose in poses], spec.error)
    final_grid = grid.refined()
    warnings, blocked = _cell_warnings(part, spec, profile, sim_backend, poses), []
    families, spaces = [], []
    for choice in spec.families:
        choice = choice.with_grip_height(poses[0].grasp.grip_height_mm)
        space = SearchSpace(part, choice, gripper, clearance_mm, [pose.part for pose in poses[1:]])
        params = space.describe()
        notes = [f"{space.family.label}: {p.note}" for p in params if p.note]
        families.append(FamilySummary(family=choice.family, label=space.family.label, params=params, free=space.names, warnings=notes))
        warnings += notes
        blocked += _unbuildable(part, space, gripper, clearance_mm)
        warnings += _other_poses(part, space, gripper, clearance_mm, poses[1:])
        spaces.append((choice, space))
    warnings += grid.warnings(spec.error)

    n_bo = sum(1 for _, space in spaces if len(space.names) >= 3)
    batch = round(WAVES * profile.sim.envs / grid.size / max(1, n_bo))
    batch = min(BATCH_LIMITS[1], max(BATCH_LIMITS[0], batch))
    searches = [_search(choice, space, spec.budget, batch, clearance_mm) for choice, space in spaces]

    search_designs = sum(s.budget for s in searches) + len(BASELINES)
    final_designs = sum(min(FINALISTS, s.budget) for s in searches) + len(BASELINES)
    k = len(poses)
    totals = PlanTotals(
        search_offsets=grid.size,
        final_offsets=final_grid.size,
        search_designs=search_designs,
        search_grasps=search_designs * grid.size * k,
        final_designs=final_designs,
        final_grasps=final_designs * final_grid.size * k,
        rounds=max((s.rounds for s in searches), default=1) + 1,
        total_grasps=(search_designs * grid.size + final_designs * final_grid.size) * k,
        poses=k,
    )
    rate = estimate.grasps_per_s
    estimate = estimate.model_copy(update={"seconds": totals.total_grasps / rate if rate else None})
    return JobPlan(
        part=part,
        families=families,
        searches=searches,
        baselines=list(BASELINES),
        grid=grid,
        final_grid=final_grid,
        totals=totals,
        estimate=estimate,
        warnings=warnings,
        blocked=blocked,
        sim_backend=sim_backend,
        poses=poses,
    )


def _search(choice: FamilyChoice, space: SearchSpace, budget: int | None, batch: int, clearance_mm: float | None) -> SearchConfig:
    """One family's search, by its number of free parameters (the table in the module docstring)."""
    d = len(space.names)
    if d == 0:
        method, budget, n_initial = "single", 1, 1
    elif d in SOBOL_BUDGETS:
        method, budget = "sobol", budget or SOBOL_BUDGETS[d]
        n_initial = budget
    else:
        method, budget = "bo", budget or BO_BUDGET
        n_initial = min(2 * d + 4, budget)
    if method == "bo":
        batch = max(1, min(batch, (budget - n_initial) // MIN_LEARNING_ROUNDS))
        patience = max(PATIENCE_PER_PARAM * d, batch)
    else:
        batch, patience = n_initial, budget
    return SearchConfig(
        key=choice.family,
        family=choice.family,
        free=space.names,
        locked=space.locks,
        ranges={name: r for name, r in choice.ranges.items() if name in space.names},
        method=method,
        n_initial=n_initial,
        budget=budget,
        batch_size=batch,
        patience=patience,
        clearance_mm=clearance_mm,
    )


def _unbuildable(part: Part, space: SearchSpace, gripper: Gripper, clearance_mm: float | None) -> list[str]:
    """Why a family has no buildable design for this part: what problems() says about its middle design (or its locked
    design). The search space's limits keep every design buildable when any is, so one design stands for them all."""
    label = space.family.label
    try:
        finger = build_finger(part, space.centre(), gripper)
    except Exception as e:  # CadQuery and pydantic raise their own types; any failure here means no finger
        return [f"{label}: no finger can be built for this part ({e})"]
    return [f"{label}: no buildable design for this part: {p}" for p in problems(part, finger, gripper, clearance_mm=clearance_mm)]


def _other_poses(part: Part, space: SearchSpace, gripper: Gripper, clearance_mm: float | None, others: list[JobPose]) -> list[str]:
    """What problems() says about a family's middle design gripping each other pose: warnings, not blockers, since a
    design that can't grip a pose only scores 0 there."""
    if not others:
        return []
    label = space.family.label
    try:
        design = space.centre()
        built = build_finger(part, design, gripper)
    except Exception:  # CadQuery and pydantic raise their own types; _unbuildable() already blocks the family
        return []
    out = []
    for pose in others:
        finger = regrip(part, pose.part, design, gripper, tip_height_mm=pose.grasp.grip_height_mm, built=built)
        found = problems(pose.part, finger, gripper, clearance_mm=clearance_mm)
        where = f"{label}, {pose.label or pose.key}"
        out += [f"{where}: the middle design can't grip this pose ({p}); a design that can't scores 0 in it" for p in found]
    return out


def _cell_warnings(part: Part, spec: JobSpec, profile: CellProfile, sim_backend: SimBackend, poses: list[JobPose]) -> list[str]:
    """Warnings that don't depend on the family: the cell, the error preset, the stock baseline, the part's model, and
    the poses the job covers."""
    out = [f"cell profile vs the sim: {m}" for m in profile.twin_mismatches()]
    if sim_backend == "mock":
        out.append("mock sim: geometry only, so its success rates are not predictions")
    preset = PRESETS.get(spec.error.preset)
    if preset is not None and preset.placeholder:
        out.append(
            f"the '{preset.label}' error preset ({preset.sigma_mm:g} mm, {preset.sigma_deg:g} deg) is a placeholder until "
            "measured on the cell"
        )
    gap = profile.gripper.stock_tip_gap_mm
    for pose in poses:
        width = pose.part.grip_width
        if width >= gap:
            where = f"{pose.label or pose.key}: " if len(poses) > 1 else ""
            out.append(
                f"{where}the stock fingers open to {gap:g} mm at the tips and the part is {width:.1f} mm wide: the stock baseline will "
                "score 0"
            )
    mesh = next((pose.part for pose in poses if pose.part.shape == "mesh"), None)
    if mesh is not None:
        out.append(f"the part is simulated as {len(mesh.pieces)} convex pieces, an approximation of its shape")
    if len(poses) > 1:
        names = ", ".join(f"{pose.label or pose.key} ({pose.weight:.0%})" for pose in poses)
        out.append(f"every design is simulated in {len(poses)} resting poses ({names}), so the run takes about {len(poses)} times as long")
        covered = sum(pose.probability or 0.0 for pose in poses)
        out.append(
            f"the poses' likelihoods (trimesh's estimate, not measured) cover {covered:.0%} of how the part comes to rest; the "
            "score assumes the cell recognises each part's pose and uses its grasp"
        )
    return out
