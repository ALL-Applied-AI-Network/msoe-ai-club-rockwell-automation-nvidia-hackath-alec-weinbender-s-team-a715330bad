"""Evaluation jobs on the API side: plan one, rank its fingers, and turn its results into a generation job's spec.

An evaluation job is a job like any other (services/jobs.py creates, lists, cancels and resumes it); the worker runs it
(services/evaluator.py). How it scores is in api/models/evaluation.py. Planning never raises for something the user can
fix: every problem is a Blocker with the evaluation step whose screen fixes it (part, poses, fingers, cell, grasps).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from api.clients.database import DatabaseClient
from api.clients.sim import sim_badge
from api.config import AppConfig
from api.db.tables import EvaluationTrialRow, PartRow, QualificationRow, RealSessionRow
from api.models import grasp
from api.models.cell_profile import DEFAULT_PROFILE, CellProfile, CellProfileVersion, Gripper
from api.models.error_model import CURVE_SIGMAS_MM, PRESETS, ErrorModel
from api.models.evaluation import (
    EVAL_FINALISTS,
    EVAL_GRASPS,
    STEP_CELL,
    STEP_FINGERS,
    STEP_GRASPS,
    STEP_PART,
    STEP_POSES,
    EvaluationGrasp,
    EvaluationPlan,
    EvaluationPosePlan,
    EvaluationResults,
    EvaluationSpec,
    EvaluationTotals,
    EvaluationTrial,
    FingerGrasp,
    GraspScore,
    PlannedFinger,
    RankedFinger,
    RankingPose,
    Rejection,
)
from api.models.finger import Finger, problems
from api.models.finger_record import FingerRecord
from api.models.grasp import GraspChoice
from api.models.job import Job
from api.models.job_pose import pose_weights
from api.models.job_spec import MAX_POSES, JobSpec, PoseGrasp
from api.models.offset_grid import OffsetGrid
from api.models.outcome import landing_caveat
from api.models.part import Part
from api.models.part_record import PartRecord
from api.models.resting_pose import is_likely
from api.models.search_plan import Blocker
from api.models.task import Task
from api.services import cell_profiles, fingers, jobs, parts

logger = logging.getLogger(__name__)

STAND_IN_MASS_G = 1.0  # poses a part with no mass yet, so a blocked plan still shows its totals
CAVEATS = [
    "the part lies on a flat table and every grasp is top-down",
    "the grasp error covers position and turn, not height: a grasp landing high or low isn't tested",
]


class WrongJobKindError(ValueError):
    """The job is a generation job, and this needs an evaluation job (or the other way round)."""


@dataclass(frozen=True)
class EvaluationPlanned:
    """A spec worked out: the plan (always there, blockers included), and what it was worked out from."""

    plan: EvaluationPlan
    profile: CellProfileVersion | None
    record: PartRecord | None
    spec: EvaluationSpec  # with the cell profile's grasp accuracy filled in where it had no error model


@dataclass
class FingerScore:
    """One finger's score in an evaluation, from its trials at an error model and task."""

    finger_id: str
    order: int  # its place in the plan, for ties
    success: float = 0.0
    capture_radius_mm: float | None = None
    n_grasps: int = 0
    stage: str = "search"
    best: dict[str, tuple[EvaluationTrial, float, float | None]] = field(default_factory=dict)  # by pose: trial, score, radius
    searched: dict[tuple[str, str], float] = field(default_factory=dict)  # (pose, grasp) -> search-grid success
    successes: dict[str, list[bool]] = field(default_factory=dict)  # by pose: the best trial's per-point success


def plan_evaluation(db: DatabaseClient, config: AppConfig, spec: EvaluationSpec) -> EvaluationPlanned:
    """The plan for an evaluation spec, as POST /api/jobs/plan shows it and POST /api/jobs stores it."""
    blockers: list[Blocker] = []
    warnings: list[str] = []
    record = version = None
    try:
        record = parts.get_part(db, spec.part_id)
    except parts.PartNotFoundError:
        blockers.append(Blocker(step=STEP_PART, reason=f"part {spec.part_id} doesn't exist: upload the part's CAD file"))
    try:
        version = cell_profiles.get_profile(db, spec.cell_profile_id)
    except cell_profiles.CellProfileNotFoundError:
        blockers.append(Blocker(step=STEP_CELL, reason=f"cell profile {spec.cell_profile_id} doesn't exist: choose a cell profile"))
    profile = version.profile if version is not None else DEFAULT_PROFILE
    spec = spec.with_error(profile.grasp_accuracy)
    if record is not None and record.confirmed_mass_g is None:
        reason = "the part has no mass yet: choose its material (or enter a density) or enter a measured mass"
        blockers.append(Blocker(step=STEP_PART, reason=reason))

    records, found = _fingers(db, spec, version)
    blockers += found
    poses: list[EvaluationPosePlan] = []
    if record is not None:
        poses, found, notes = _poses(db, spec, record, profile)
        blockers += found
        warnings += notes

    gripper = profile.gripper
    clearance = record.clearance_mm if record is not None else None
    checked = grips(records, poses, gripper, clearance)
    rejections = [
        Rejection(finger_id=fid, pose_key=pk, grasp_key=gk, reasons=reasons) for (fid, pk, gk), (_, reasons) in checked.items() if reasons
    ]
    parts_seen = [g.part for pose in poses for g in pose.grasps]
    grid = OffsetGrid.for_parts(parts_seen, spec.error) if parts_seen else OffsetGrid()
    final_grid = grid.refined()
    combinations, simulated = len(checked), sum(1 for _, reasons in checked.values() if not reasons)
    groups = sum(len(pose.grasps) for pose in poses)
    finalists = min(EVAL_FINALISTS, sum(1 for r in records if r.source != "stock")) + sum(1 for r in records if r.source == "stock")
    final_grasps = finalists * len(poses) * final_grid.size
    totals = EvaluationTotals(
        fingers=len(records),
        combinations=combinations,
        simulated=simulated,
        search_offsets=grid.size,
        final_offsets=final_grid.size,
        search_grasps=simulated * grid.size,
        final_grasps=final_grasps,
        total_grasps=simulated * grid.size + final_grasps,
        batches=2 * groups,
    )
    badge = sim_badge(config.sim.backend)
    estimate = jobs.throughput(db, config, badge)
    rate = estimate.grasps_per_s
    estimate = estimate.model_copy(update={"seconds": totals.total_grasps / rate if rate else None})
    warnings += _warnings(spec, profile, badge, poses, records, rejections)
    force, notes = jobs.grip_force(profile.grip_force_n, record)
    warnings += notes
    blockers.sort(key=lambda b: b.step)
    first = next((g.part for pose in poses for g in pose.grasps), None)
    plan = EvaluationPlan(
        part=first or Part(),
        poses=poses,
        fingers=[PlannedFinger(finger_id=r.id, code=r.code, name=r.name, source=r.source, family=r.family) for r in records],
        rejections=rejections,
        grid=grid,
        final_grid=final_grid,
        totals=totals,
        estimate=estimate,
        warnings=warnings,
        blocked=[b.reason for b in blockers],
        blockers=blockers,
        sim_backend=badge,
        grip_force_n=force,
    )
    return EvaluationPlanned(plan=plan, profile=version, record=record, spec=spec)


def _fingers(db: DatabaseClient, spec: EvaluationSpec, version: CellProfileVersion | None) -> tuple[list[FingerRecord], list[Blocker]]:
    """The fingers to try: the spec's, or every unarchived one for the cell; the cell's stock fingers always, first."""
    if version is None:
        return [], []
    blockers = []
    if spec.finger_ids is None:
        chosen = fingers.compatible_fingers(db, version.name)
    else:
        chosen = []
        for finger_id in spec.finger_ids:
            try:
                record = fingers.get_finger(db, finger_id)
            except fingers.FingerNotFoundError:
                blockers.append(Blocker(step=STEP_FINGERS, reason=f"finger {finger_id} isn't in the library"))
                continue
            if record.cell_profile_name.lower() != version.name.lower():
                reason = f"{record.code} ({record.name}) fits the {record.cell_profile_name!r} cell, not {version.name!r}"
                blockers.append(Blocker(step=STEP_FINGERS, reason=reason))
                continue
            chosen.append(record)
        stock = [r for r in fingers.compatible_fingers(db, version.name) if r.source == "stock"]
        chosen = [r for r in stock if r.id not in {c.id for c in chosen}] + chosen
    if not any(r.source != "stock" for r in chosen) and not blockers:
        blockers.append(
            Blocker(step=STEP_FINGERS, reason=f"the {version.name!r} cell has no fingers in the library besides its stock fingers")
        )
    return sorted(chosen, key=lambda r: (r.source != "stock", r.number)), blockers


def _poses(
    db: DatabaseClient, spec: EvaluationSpec, record: PartRecord, profile: CellProfile
) -> tuple[list[EvaluationPosePlan], list[Blocker], list[str]]:
    """The resting poses to cover, primary (the likeliest) first, each with its grasps and the part as the gripper meets
    it at each; what blocks them; and warnings. Without poses in the spec: the part's likely ones (or its likeliest)."""
    blockers, warnings = [], []
    if spec.poses:
        chosen = [(p.pose, p.grasp) for p in spec.poses]
    else:
        listed = parts.resting_poses_of(record)
        likely = [i for i, pose in enumerate(listed) if pose.source == "stable" and is_likely(pose)]
        chosen = [(i, None) for i in likely[:MAX_POSES] or [0]]
    try:
        resting = parts.resolve_poses(record, [choice for choice, _ in chosen])
    except parts.PartInputError as e:
        return [], [Blocker(step=STEP_POSES, reason=f"resting pose: {e}")], []
    entries = sorted(
        zip(chosen, resting, strict=True), key=lambda e: (-(e[1].probability or 0.0), e[0][0] if isinstance(e[0][0], int) else 0)
    )
    weights = pose_weights([r.probability for _, r in entries])
    posed = record if record.confirmed_mass_g is not None else record.model_copy(update={"mass_g": STAND_IN_MASS_G})
    try:
        mesh = parts.load_mesh(record)
    except OSError as e:
        return [], [Blocker(step=STEP_PART, reason=f"the part can't be posed ({e}): upload its CAD file again")], []
    poses = []
    for i, (((choice, locked), rest), weight) in enumerate(zip(entries, weights, strict=True)):
        where = f" ({rest.label})" if len(entries) > 1 else ""
        candidates: list[tuple[GraspChoice, list[str]]] = []
        if locked is not None:
            candidate = parts.check_grasp(
                db,
                record.id,
                profile,
                angle_deg=locked.angle_deg,
                picks=locked.picks,
                grip_height_mm=locked.grip_height_mm,
                pose=rest,
                centre_mm=locked.centre_mm if locked.span_mm is not None else None,
                span_mm=locked.span_mm,
            )
            if candidate.verdict == "blocked":
                reasons = candidate.blocked_reasons or [f"the grasp at {locked.angle_deg:g} deg doesn't fit this gripper"]
                blockers += [Blocker(step=STEP_GRASPS, reason=f"grasp{where}: {r}") for r in reasons]
            else:
                candidates.append((locked, candidate.warnings))
        else:
            proposals = parts.propose_grasps(db, record.id, profile, rest)
            usable = [c for c in proposals.candidates if c.verdict != "blocked"][:EVAL_GRASPS]
            if not usable:
                why = proposals.nothing_fits.reason if proposals.nothing_fits is not None else "no grasp direction fits this gripper"
                warnings.append(f"pose{where or ' ' + (rest.label or '')}: {why}; every finger scores 0 in it")
            candidates += [
                (GraspChoice(angle_deg=c.angle_deg, centre_mm=c.centre_mm, span_mm=c.span_mm, source="auto"), c.warnings) for c in usable
            ]
        grasps = []
        for j, (g, notes) in enumerate(candidates):
            try:
                part = grasp.posed_part(posed, g, profile.pad_friction, mesh, pose=rest)
            except ValueError as e:
                blockers.append(Blocker(step=STEP_PART, reason=f"the part can't be posed ({e}): upload its CAD file again"))
                continue
            grasps.append(EvaluationGrasp(key=f"g{j}", grasp=g, part=part, warnings=notes))
        poses.append(
            EvaluationPosePlan(
                key=f"p{i}", label=rest.label, choice=choice, probability=rest.probability, weight=weight, resting=rest, grasps=grasps
            )
        )
    if poses and not any(pose.grasps for pose in poses) and not blockers:
        blockers.append(Blocker(step=STEP_GRASPS, reason="no grasp fits the part in any of the chosen poses on this gripper"))
    return poses, blockers, warnings


def grips(
    records: list[FingerRecord], poses: list[EvaluationPosePlan], gripper: Gripper, clearance_mm: float | None
) -> dict[tuple[str, str, str], tuple[Finger | None, list[str]]]:
    """Every finger at every grasp of every pose: (the finger gripping there, or None for the stock fingers; and what
    rules it out there, empty if nothing does), by (finger id, pose key, grasp key). Shared by the plan and the run, so
    both rule out exactly the same combinations."""
    out = {}
    for record in records:
        built = None
        if record.source == "generated":
            try:
                built = record.geometry(gripper)
            except Exception as e:  # CadQuery raises its own types on degenerate geometry
                logger.warning("Finger %s can't be built: %s", record.code, e)
                for pose in poses:
                    for g in pose.grasps:
                        out[(record.id, pose.key, g.key)] = (None, [f"the finger can't be built ({e})"])
                continue
        for pose in poses:
            for g in pose.grasps:
                out[(record.id, pose.key, g.key)] = _grip(record, g, gripper, clearance_mm, built)
    return out


def _grip(record: FingerRecord, g: EvaluationGrasp, gripper: Gripper, clearance_mm: float | None, built: Finger | None):
    if record.source == "stock":
        return None, []  # the robot's own fingers: the sim's model of them, never ruled out
    try:
        finger = record.grip(g.part, gripper, tip_height_mm=g.grasp.grip_height_mm, built=built)
        return finger, problems(g.part, finger, gripper, clearance_mm=clearance_mm)
    except Exception as e:  # any failure here means this grasp can't be worked out for the finger
        return None, [f"no grasp can be worked out ({e})"]


def _warnings(
    spec: EvaluationSpec,
    profile: CellProfile,
    badge: str,
    poses: list[EvaluationPosePlan],
    records: list[FingerRecord],
    rejections: list[Rejection],
) -> list[str]:
    out = [f"cell profile vs the sim: {m}" for m in profile.twin_mismatches()]
    if badge == "mock":
        out.append("mock sim: geometry only, so its success rates are not predictions")
    preset = PRESETS.get(spec.error.preset)
    if preset is not None and preset.placeholder:
        accuracy = f"{preset.sigma_mm:g} mm, {preset.sigma_deg:g} deg"
        out.append(f"the '{preset.label}' grasp accuracy ({accuracy}) is a placeholder until measured on the cell")
    gap = profile.gripper.stock_tip_gap_mm
    for pose in poses:
        wide = [g for g in pose.grasps if g.part.grip_width >= gap]
        if wide and any(r.source == "stock" for r in records):
            out.append(
                f"{pose.label or pose.key}: the stock fingers open to {gap:g} mm at the tips, too narrow for {len(wide)} of its grasps"
            )
    if any(g.part.shape == "mesh" for pose in poses for g in pose.grasps):
        out.append("the part is simulated as convex pieces, an approximation of its shape")
    keys = {(p.key, g.key) for p in poses for g in p.grasps}
    for r in records:
        ruled_out = {(rej.pose_key, rej.grasp_key) for rej in rejections if rej.finger_id == r.id}
        if r.source != "stock" and keys and ruled_out >= keys:
            out.append(f"{r.code} ({r.name}) can't grip the part at any grasp: it scores 0")
    if len(poses) > 1:
        names = ", ".join(f"{p.label or p.key} ({p.weight:.0%})" for p in poses)
        out.append(f"every finger is simulated in {len(poses)} resting poses ({names}); the score assumes the cell recognises the pose")
    return out


def load_trials(db: DatabaseClient, job_id: str, stage: str | None = None) -> list[EvaluationTrial]:
    query = select(EvaluationTrialRow).where(EvaluationTrialRow.job_id == job_id).order_by(EvaluationTrialRow.number)
    if stage is not None:
        query = query.where(EvaluationTrialRow.stage == stage)
    with db.session() as s:
        return [EvaluationTrial.model_validate(row) for row in s.scalars(query)]


def score_fingers(plan: EvaluationPlan, trials: list[EvaluationTrial], error: ErrorModel, task: Task) -> list[FingerScore]:
    """Every planned finger's score, best first: in each pose its final trial if it has one, else its best grasp on the
    search grid (by success, then capture radius, then the better-ranked grasp); weighted over the poses. A pose it has
    no trial in scores 0 there."""
    scores = {f.finger_id: FingerScore(finger_id=f.finger_id, order=i) for i, f in enumerate(plan.fingers)}
    weights = {pose.key: pose.weight for pose in plan.poses}
    grasp_order = {(pose.key, g.key): j for pose in plan.poses for j, g in enumerate(pose.grasps)}
    scored: dict[tuple[str, str], list[tuple[EvaluationTrial, float, float | None, list[bool]]]] = {}
    for trial in trials:
        if trial.finger_id not in scores:
            continue
        grid = plan.final_grid if trial.stage == "final" else plan.grid
        success = task.success(trial.outcomes())
        rate, radius = grid.expected_success(success, error), grid.capture_radius(success)
        scored.setdefault((trial.finger_id, trial.pose_key), []).append((trial, rate, radius, success))
        if trial.stage == "search":
            scores[trial.finger_id].searched[(trial.pose_key, trial.grasp_key)] = rate
    for (finger_id, pose_key), found in scored.items():
        finals = [f for f in found if f[0].stage == "final"]
        pool = finals or found
        trial, rate, radius, success = min(
            pool, key=lambda f: (-f[1], -(f[2] if f[2] is not None else -1.0), grasp_order.get((pose_key, f[0].grasp_key), 99))
        )
        scores[finger_id].best[pose_key] = (trial, rate, radius)
        scores[finger_id].successes[pose_key] = success
    for score in scores.values():
        score.success = sum(weights.get(pk, 0.0) * rate for pk, (_, rate, _) in score.best.items())
        radii = [radius for _, _, radius in score.best.values()]
        covered = len(score.best) == len(plan.poses) and plan.poses
        score.capture_radius_mm = min(radii) if covered and None not in radii else None
        score.n_grasps = sum(trial.n_grasps for trial, _, _ in score.best.values())
        score.stage = "final" if score.best and all(t.stage == "final" for t, _, _ in score.best.values()) else "search"
    return sorted(scores.values(), key=lambda s: (-s.success, -(s.capture_radius_mm if s.capture_radius_mm is not None else -1.0), s.order))


def ranking(db: DatabaseClient, job_id: str, *, error: ErrorModel | None = None, task: Task | None = None) -> EvaluationResults:
    """The results page of an evaluation job: its fingers ranked, at the job's own error model and task or at others
    (re-scored from the stored outcomes; nothing is simulated or stored). Raises WrongJobKindError for a generation job."""
    job = _evaluation_job(db, job_id)
    plan, spec = job.plan, job.spec
    error, task = error or spec.error, task or spec.task
    trials = load_trials(db, job_id)
    scores = score_fingers(plan, trials, error, task)
    planned = {f.finger_id: f for f in plan.fingers}
    current = {r.id: r for r in _records(db, list(planned))}
    quals = _qualifications(db, list(planned), job.part_id)
    out = []
    for rank, score in enumerate(scores, 1):
        snapshot = planned[score.finger_id]
        record = current.get(score.finger_id)
        best = []
        for pose in plan.poses:
            if pose.key not in score.best:
                continue
            trial, rate, radius = score.best[pose.key]
            g = plan.grasp(pose.key, trial.grasp_key).grasp
            best.append(
                FingerGrasp(
                    pose_key=pose.key,
                    pose_label=pose.label,
                    grasp_key=trial.grasp_key,
                    angle_deg=g.angle_deg,
                    centre_mm=g.centre_mm,
                    span_mm=g.span_mm,
                    tip_height_mm=trial.tip_height_mm,
                    jaw_close_mm=trial.jaw_close_mm,
                    success=rate,
                    capture_radius_mm=radius,
                    stage=trial.stage,
                )
            )
        grasps = [
            GraspScore(
                pose_key=pose.key,
                grasp_key=g.key,
                success=score.searched.get((pose.key, g.key)),
                reasons=plan.rejected(score.finger_id, pose.key, g.key) or [],
            )
            for pose in plan.poses
            for g in pose.grasps
        ]
        qual = quals.get(score.finger_id)
        out.append(
            RankedFinger(
                rank=rank,
                finger_id=score.finger_id,
                code=snapshot.code,
                name=record.name if record is not None else snapshot.name,
                source=snapshot.source,
                family=snapshot.family,
                success=score.success,
                capture_radius_mm=score.capture_radius_mm,
                n_grasps=score.n_grasps,
                stage=score.stage,
                best=best,
                grasps=grasps,
                curve=_curve(plan, score, error),
                qualification_id=qual[0] if qual else None,
                measured_success=qual[1] if qual else None,
                real_trials=qual[2] if qual else 0,
            )
        )
    with db.session() as s:
        part_name = s.scalar(select(PartRow.name).where(PartRow.id == job.part_id))
    return EvaluationResults(
        job_id=job.id,
        experiment_id=job.experiment_id,
        name=job.name,
        status=job.status,
        sim_backend=job.sim_backend,
        part_id=job.part_id,
        part_name=part_name,
        cell_profile_id=job.cell_profile_id,
        error=error,
        task=task,
        rescored=error != spec.error or task != spec.task,
        final=any(t.stage == "final" for t in trials),
        poses=[RankingPose(key=p.key, label=p.label, weight=p.weight, grasps=p.grasps) for p in plan.poses],
        fingers=out,
        warnings=plan.warnings + CAVEATS + _landing_warning(job, trials),
    )


def _landing_warning(job: Job, trials: list[EvaluationTrial]) -> list[str]:
    if job.sim_backend == "mock":
        return []
    note = landing_caveat([t.outcomes() for t in trials])
    return [] if note is None else [note]


def _curve(plan: EvaluationPlan, score: FingerScore, error: ErrorModel) -> dict[str, float]:
    """Success at each CURVE_SIGMAS_MM, at the finger's best grasp in each pose."""
    weights = {pose.key: pose.weight for pose in plan.poses}
    out = {}
    for sigma in CURVE_SIGMAS_MM:
        at = error.at_sigma(sigma)
        total = 0.0
        for pose_key, (trial, _, _) in score.best.items():
            grid = plan.final_grid if trial.stage == "final" else plan.grid
            total += weights.get(pose_key, 0.0) * grid.expected_success(score.successes[pose_key], at)
        out[f"{sigma:g}"] = total
    return out


def generate_spec(db: DatabaseClient, job_id: str, *, finger_id: str | None = None) -> JobSpec:
    """A generation job's spec from an evaluation job: the same part, cell, task, grasp accuracy and poses, each pose with
    the grasp `finger_id` scored best at (when given and it grips there), else the pose's best grasp proposal. For the
    wizard to edit and POST /api/jobs; nothing is stored or started."""
    job = _evaluation_job(db, job_id)
    plan = job.plan
    best: dict[str, str] = {}
    if finger_id is not None:
        if finger_id not in {f.finger_id for f in plan.fingers}:
            raise fingers.FingerNotFoundError(finger_id)
        score = next(s for s in score_fingers(plan, load_trials(db, job_id), job.spec.error, job.spec.task) if s.finger_id == finger_id)
        best = {pose_key: trial.grasp_key for pose_key, (trial, _, _) in score.best.items()}
    poses = []
    for pose in plan.poses:
        if not pose.grasps or pose.choice is None:
            continue
        key = best.get(pose.key, pose.grasps[0].key)
        poses.append(PoseGrasp(pose=pose.choice, grasp=plan.grasp(pose.key, key).grasp))
    with db.session() as s:
        part_name = s.scalar(select(PartRow.name).where(PartRow.id == job.part_id)) or "part"
    if Path(part_name).suffix.lower() in parts.CAD_SUFFIXES:
        part_name = Path(part_name).stem
    return JobSpec(
        name=f"{part_name} - new finger",
        part_id=job.part_id,
        cell_profile_id=job.cell_profile_id,
        task=job.spec.task,
        error=job.spec.error,
        poses=poses,
    )


def card_scores(db: DatabaseClient, job: Job) -> tuple[tuple[str, float, float | None] | None, tuple[str, float, float | None] | None]:
    """A finished evaluation job's card: its best finger and its stock fingers, as (code, success, capture radius)."""
    plan = job.plan
    scores = score_fingers(plan, load_trials(db, job.id), job.spec.error, job.spec.task)
    codes = {f.finger_id: (f.code, f.source) for f in plan.fingers}
    best = next(((codes[s.finger_id][0], s.success, s.capture_radius_mm) for s in scores if s.best), None)
    stock = next(((codes[s.finger_id][0], s.success, s.capture_radius_mm) for s in scores if codes[s.finger_id][1] == "stock"), None)
    return best, stock


def _evaluation_job(db: DatabaseClient, job_id: str) -> Job:
    job = jobs.get_job(db, job_id)
    if job.kind != "evaluation":
        raise WrongJobKindError(f"{job.experiment_id} is a generation job, not an evaluation")
    return job


def _records(db: DatabaseClient, finger_ids: list[str]) -> list[FingerRecord]:
    out = []
    for finger_id in finger_ids:
        try:
            out.append(fingers.get_finger(db, finger_id))
        except fingers.FingerNotFoundError:
            continue
    return out


def _qualifications(db: DatabaseClient, finger_ids: list[str], part_id: str) -> dict[str, tuple[int, float | None, int]]:
    """By finger: (qualification id, measured success over every session, real trials) on this part."""
    with db.session() as s:
        rows = list(
            s.scalars(select(QualificationRow).where(QualificationRow.part_id == part_id, QualificationRow.finger_id.in_(finger_ids)))
        )
        sessions = list(s.scalars(select(RealSessionRow).where(RealSessionRow.qualification_id.in_([r.id for r in rows]))))
    out = {}
    for row in rows:
        mine = [x for x in sessions if x.qualification_id == row.id]
        trials = sum(x.trials for x in mine)
        out[row.finger_id] = (row.id, sum(x.successes for x in mine) / trials if trials else None, trials)
    return out
