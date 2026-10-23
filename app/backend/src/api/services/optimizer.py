"""Runs one experiment: a batch Bayesian optimisation per finger family in the simulator, then the final dense test.

Every design is tried at every point of the job's fixed offset grid (api/models/offset_grid.py), and scored from its raw
outcomes by the task (Task.success) and the error model (OffsetGrid.expected_success). The searches the plan lists
(api/models/search_plan.py) run side by side, in rounds, and a round is one sim request carrying every active search's
designs, so the sim's start-up and network cost is paid once per round however many families there are:

- round 0: the stock and imprint baselines, every locked design (a family with nothing left free), and each search's
  first designs, a Sobol sample (for a Sobol sweep, the whole sweep);
- later rounds: each BO search still running fits its own GP to its own scores and proposes batch_size designs with
  qLogNoisyExpectedImprovement, or a Sobol sample that round if the fit fails. A search stops when its budget is spent,
  or when its last `patience` designs gained less than MIN_GAIN on its best (after at least one batch).

Each round is checkpointed in one transaction, so a crashed, cancelled or interrupted job resumes after its last round
and never redoes one. The final test re-runs the top FINALISTS of each search (a locked design is its search's only one)
and both baselines on the dense grid. They're labelled D1, D2, ... by final score, capture radius breaking ties, and
STOCK and IMP; those trials, the result with D1's printable CAD, and the run metadata are written in one transaction, so
finishing is all or nothing and can simply be run again.

A job covering several resting poses (api/models/job_pose.py) searches in the primary pose's space and sends one sim
request per pose each round: every design is built once, for the primary pose, and regripped for each other
(finger.regrip()). A design's score is weighted over the poses; one that can't grip a pose scores 0 there.
"""

import logging
import os
import platform
import subprocess
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import botorch
import cadquery
import gpytorch
import torch
from botorch.acquisition.logei import qLogNoisyExpectedImprovement
from botorch.fit import fit_gpytorch_mll
from botorch.models import SingleTaskGP
from botorch.models.transforms.outcome import Standardize
from botorch.optim import optimize_acqf
from gpytorch.mlls import ExactMarginalLogLikelihood
from sqlalchemy import delete, func, select, update
from torch.quasirandom import SobolEngine

from api.clients.cad import CadClient, FingerExport
from api.clients.database import DatabaseClient
from api.clients.sim import SimClient, SimError, SimSettings
from api.db.tables import JobRow, ResultRow, RunMetaRow, TrialRow
from api.models.cell_profile import CellProfileVersion, Gripper
from api.models.design import Design
from api.models.export_check import ExportCheck
from api.models.finger import Finger, build_finger, problems, regrip
from api.models.job import Job, Trial
from api.models.job_pose import JobPose, score_poses
from api.models.offset_grid import OffsetGrid
from api.models.outcome import Outcomes
from api.models.printed_finger import finger_id
from api.models.results import BASELINE_LABELS, file_stem
from api.models.search_plan import BASELINES, FINALISTS, SearchConfig
from api.models.search_space import SearchSpace
from api.services import cell_profiles
from api.services.jobs import JobNotFoundError, get_job, update_job
from api.services.results import grasp_pose_for, print_sheet

logger = logging.getLogger(__name__)

BASELINE_SEARCH = "baseline"  # the search key the stock and imprint trials are stored under
GP_RESTARTS, GP_RAW_SAMPLES = 8, 256
SEED_STRIDE = 1000  # seeds of different searches in one job stay this far apart
TRACEBACK_CHARS = 4000


class JobRunError(RuntimeError):
    """A failure the run can explain in one line, with the input step that fixes it when there is one."""

    def __init__(self, line: str, step: int | None = None):
        super().__init__(line)
        self.line, self.step = line, step


@dataclass(frozen=True)
class _Run:
    """What one worker runs a job with, loaded once."""

    job: Job
    profile: CellProfileVersion
    gripper: Gripper
    spaces: dict[str, SearchSpace]  # by search key
    settings: SimSettings
    clearance_mm: float | None  # the part's clearance on the table, which the searched and locked designs must keep

    @property
    def transport(self) -> bool:
        return self.settings.transport is not None


def run_job(db: DatabaseClient, job_id: str, *, sim: SimClient, cad: CadClient, outputs_dir: Path) -> None:
    """Run or resume a job to completion. A failure is stored on the job (status 'failed', the traceback, a one-line
    failure and the input step that fixes it), not raised. A job that's already done is left alone."""
    started = time.time()
    try:
        job = get_job(db, job_id)
    except JobNotFoundError:
        logger.error("Job %s: not found", job_id)
        return
    if job.status == "done":
        logger.info("Job %s: already done", job_id)
        return
    update_job(db, job_id, status="running", pid=os.getpid(), error=None, failure=None, failed_step=None)
    logger.info("Job %s (%s): running on the %s sim", job_id, job.experiment_id, sim.backend)
    try:
        if sim.badge != job.sim_backend:
            # A resumed job keeps its badge, so finishing it on another sim would label one sim's results as the other's.
            raise JobRunError(
                f"this experiment runs on the {job.sim_backend} sim, but this worker has the {sim.badge} one: set SIM_BACKEND "
                "back to resume it, or duplicate it to run on this sim"
            )
        run = _load(db, job)
        if not _search(db, run, sim) or _cancelled(db, job_id):
            return
        _finalize(db, run, sim=sim, cad=cad, outputs_dir=outputs_dir, started=started)
        logger.info("Job %s: done in %.0f s", job_id, time.time() - started)
    except Exception as e:
        logger.exception("Job %s: failed", job_id)
        line, step = _failure(e)
        update_job(db, job_id, status="failed", error=traceback.format_exc()[-TRACEBACK_CHARS:], failure=line, failed_step=step)


def _load(db: DatabaseClient, job: Job) -> _Run:
    try:
        profile = cell_profiles.get_profile(db, job.cell_profile_id)
    except cell_profiles.CellProfileNotFoundError:
        raise JobRunError(f"cell profile {job.cell_profile_id} no longer exists", step=4) from None
    gripper = profile.profile.gripper
    searches = job.plan.searches
    return _Run(
        job=job,
        profile=profile,
        gripper=gripper,
        spaces={search.key: search.space(job.part, gripper, [pose.part for pose in job.poses[1:]]) for search in searches},
        settings=SimSettings(grip_force_n=job.plan.grip_force_n, transport=job.spec.task.transport),
        clearance_mm=searches[0].clearance_mm if searches else None,
    )


def _search(db: DatabaseClient, run: _Run, sim: SimClient) -> bool:
    """Rounds until every search has stopped. False if the job was cancelled."""
    job_id, grid = run.job.id, run.job.plan.grid
    while True:
        trials = _load_trials(db, job_id, "search")
        number = max(t.round for t in trials) + 1 if trials else 0
        designs = _round_designs(run, trials, number)
        if not designs:
            return True
        if _cancelled(db, job_id):
            return False
        _run_round(db, run, sim, grid, number, designs, trials)


def _round_designs(run: _Run, trials: list[Trial], number: int) -> list[tuple[str, Design]]:
    """The (search key, design) pairs of round `number`: see the module docstring."""
    seed = run.job.spec.seed
    out: list[tuple[str, Design]] = []
    if number == 0:
        out += [(BASELINE_SEARCH, Design(kind=kind)) for kind in BASELINES]
    for i, search in enumerate(run.job.plan.searches):
        space = run.spaces[search.key]
        mine = [t for t in trials if t.search == search.key]
        if number == 0:
            if search.method == "single":
                out.append((search.key, space.locked_design()))
            else:
                out += [(search.key, space.from_unit(u)) for u in _sobol(len(space.names), search.n_initial, seed + i * SEED_STRIDE)]
        elif search.method == "bo" and _stop_reason(search, mine) is None:
            q = min(search.batch_size, search.budget - len(mine))
            points = _propose(space, mine, q, seed=seed + i * SEED_STRIDE, round_number=number)
            out += [(search.key, space.from_unit(u)) for u in points]
    return out


def _stop_reason(search: SearchConfig, trials: list[Trial]) -> str | None:
    """SearchConfig.stop_reason over the search's own search-grid trials, in the order they were evaluated."""
    return search.stop_reason([t.success_rate for t in sorted(trials, key=lambda t: t.number)])


def _propose(space: SearchSpace, trials: list[Trial], q: int, *, seed: int, round_number: int) -> list[list[float]]:
    """The next q points of the search's unit cube: the batch BoTorch expects to improve most on the best score so far,
    chosen one point at a time with the earlier ones treated as pending, so the batch spreads out instead of piling onto
    one optimum. Falls back to continuing the search's Sobol sequence if the GP can't be fitted or optimised."""
    d = len(space.names)
    torch.manual_seed(seed + round_number)
    try:
        x = torch.tensor([space.to_unit(Design(kind="search", params=t.params)) for t in trials], dtype=torch.double)
        y = torch.tensor([[t.success_rate] for t in trials], dtype=torch.double)
        model = SingleTaskGP(x, y, outcome_transform=Standardize(m=1))
        fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
        acquisition = qLogNoisyExpectedImprovement(model, X_baseline=x, prune_baseline=True)
        bounds = torch.stack([torch.zeros(d, dtype=torch.double), torch.ones(d, dtype=torch.double)])
        candidates, _ = optimize_acqf(
            acquisition, bounds=bounds, q=q, num_restarts=GP_RESTARTS, raw_samples=GP_RAW_SAMPLES, sequential=True
        )
        return candidates.tolist()
    except Exception:
        logger.warning("GP proposal failed; using a Sobol sample this round", exc_info=True)
        return _sobol(d, q, seed, skip=len(trials))


def _sobol(d: int, n: int, seed: int, skip: int = 0) -> list[list[float]]:
    """n points of the search's own scrambled Sobol sequence, after the first `skip`: round 0 takes the start, and a
    failed GP fit continues it, so no point repeats."""
    engine = SobolEngine(d, scramble=True, seed=seed)
    if skip:
        engine.fast_forward(skip)
    return engine.draw(n, dtype=torch.double).tolist()


def _run_round(
    db: DatabaseClient,
    run: _Run,
    sim: SimClient,
    grid: OffsetGrid,
    number: int,
    designs: list[tuple[str, Design]],
    earlier: list[Trial],
) -> None:
    """Simulate one round and store it, with the job's progress, in one transaction: a round is checkpointed whole or
    not at all."""
    job_id = run.job.id
    outcomes, seconds = _simulate(run, sim, [design for _, design in designs], grid)
    first = _next_number(db, job_id)
    rows = [
        _trial_row(run, grid, first + i, number, key, design, by_pose, sec)
        for i, ((key, design), by_pose, sec) in enumerate(zip(designs, outcomes, seconds, strict=True))
    ]
    searched = [(t.success_rate, t.number) for t in earlier if t.search != BASELINE_SEARCH]
    searched += [(row.success_rate, row.number) for row in rows if row.search != BASELINE_SEARCH]
    best_value, best_trial = max(searched, key=lambda s: (s[0], -s[1])) if searched else (None, None)
    with db.session() as s:
        s.add_all(rows)
        s.flush()
        n_done = s.scalar(select(func.count()).select_from(TrialRow).where(TrialRow.job_id == job_id))
        s.execute(
            update(JobRow).where(JobRow.id == job_id).values(n_done=n_done, round=number + 1, best_value=best_value, best_trial=best_trial)
        )
    logger.info("Job %s: round %d done: %d designs in %.1f s, best %.3f", job_id, number, len(rows), sum(seconds), best_value or 0.0)


def _simulate(run: _Run, sim: SimClient, designs: list[Design], grid: OffsetGrid) -> tuple[list[list[Outcomes]], list[float]]:
    """Every design at every grid point in every resting pose the job covers, in one sim request per pose: (outcomes per
    pose, sim seconds) per design. Each design is built once, for the primary pose; one that fails the geometry checks
    (finger.problems) there isn't sent at all, and one that can't grip another pose isn't sent for it. A design fails
    every grasp it wasn't sent for, and its seconds count only the requests it was in, which keeps a design that wasn't
    simulated out of the throughput estimate. The stock fingers are the robot's own: the sim gets None for them."""
    poses, gripper, n = run.job.poses, run.gripper, grid.size
    primary = poses[0].part
    built: list[Finger | None] = []  # per design: its finger for the primary pose; None for the stock fingers
    usable: list[bool] = []
    for design in designs:
        if design.kind == "stock":
            built.append(None)
            usable.append(True)
            continue
        try:
            finger = build_finger(primary, design, gripper)
            found = problems(primary, finger, gripper, clearance_mm=_clearance(run, design))
        except Exception as e:  # CadQuery and pydantic raise their own types; any failure here means no finger
            finger, found = None, [f"no finger can be built ({e})"]
        if found:
            logger.info("Job %s: not simulating a %s design (%s): %s", run.job.id, design.kind, design.params, "; ".join(found))
        built.append(finger)
        usable.append(not found)
    outcomes: list[list[Outcomes | None]] = [[None] * len(poses) for _ in designs]
    seconds = [0.0] * len(designs)
    offsets = grid.points()
    for k, pose in enumerate(poses):
        fingers, sent = [], []
        for i, design in enumerate(designs):
            if not usable[i]:
                continue
            finger = built[i]
            if k > 0 and finger is not None:
                finger, found = _regripped(run, design, finger, pose)
                if found:
                    why = "; ".join(found)
                    logger.info("Job %s: a %s design (%s) can't grip %s: %s", run.job.id, design.kind, design.params, pose.key, why)
                    continue
            fingers.append(finger)
            sent.append(i)
        started = time.perf_counter()
        results = sim.run_batch(pose.part, fingers, offsets, run.settings) if fingers else []
        share = (time.perf_counter() - started) / len(fingers) if fingers else 0.0
        if len(results) != len(fingers):
            raise SimError(f"the sim answered for {len(results)} designs out of {len(fingers)}")
        for i, result in zip(sent, results, strict=True):
            outcomes[i][k] = result
            seconds[i] += share
    dropped = Outcomes.dropped(n, run.transport)
    return [[out if out is not None else dropped for out in by_pose] for by_pose in outcomes], seconds


def _regripped(run: _Run, design: Design, built: Finger, pose: JobPose) -> tuple[Finger | None, list[str]]:
    """The primary pose's finger gripping another pose, and what rules it out there."""
    try:
        finger = regrip(run.job.poses[0].part, pose.part, design, run.gripper, tip_height_mm=pose.grasp.grip_height_mm, built=built)
        return finger, problems(pose.part, finger, run.gripper, clearance_mm=_clearance(run, design))
    except Exception as e:  # as in _simulate: any failure means this pose can't be gripped
        return None, [f"no grasp can be worked out ({e})"]


def _clearance(run: _Run, design: Design) -> float | None:
    """The part's clearance on the table, which the searched and locked designs must keep (the baselines don't)."""
    return run.clearance_mm if design.kind in ("search", "locked") else None


def _trial_row(
    run: _Run,
    grid: OffsetGrid,
    number: int,
    round_number: int,
    search: str,
    design: Design,
    outcomes: list[Outcomes],
    seconds: float,
    *,
    final: bool = False,
) -> TrialRow:
    """A design's trial on a grid, from its outcomes in each of the job's poses, scored at the job's own task and error
    model and weighted over the poses. Final-test trials are labelled once they're all scored."""
    successes = [run.job.spec.task.success(out) for out in outcomes]
    rate, radius, _ = score_poses(successes, run.job.poses, grid, run.job.spec.error)
    primary = outcomes[0]
    return TrialRow(
        job_id=run.job.id,
        number=number,
        round=round_number,
        search=search,
        grid="final" if final else "search",
        kind=design.kind,
        label=None,
        params=None if design.params is None else design.params.model_dump(),
        success_rate=rate,
        capture_radius_mm=radius,
        n_grasps=grid.size * len(outcomes),
        n_success=sum(sum(success) for success in successes),
        held=primary.held,
        in_hand=[None if pose is None else list(pose) for pose in primary.in_hand],
        held_after_transport=primary.held_after_transport,
        pose_outcomes=outcomes[1:] or None,
        duration=seconds,
    )


def _finalize(db: DatabaseClient, run: _Run, *, sim: SimClient, cad: CadClient, outputs_dir: Path, started: float) -> None:
    """The final test: re-test the finalists of every search and both baselines together on the dense grid, so the
    winner isn't just the design that happened to suit the search grid and the comparison is like for like. Then label
    them, export D1's printable CAD, and store the labelled trials, the result and the run metadata together."""
    job, plan = run.job, run.job.plan
    update_job(db, job.id, status="finalizing")
    trials = _load_trials(db, job.id, "search")
    finalists = [t for search in plan.searches for t in _ranked([t for t in trials if t.search == search.key])[:FINALISTS]]
    if not finalists:
        raise JobRunError("the search produced no designs", step=6)
    designs = [(t.search, Design(kind=t.kind, params=t.params)) for t in finalists]
    designs += [(BASELINE_SEARCH, Design(kind=kind)) for kind in BASELINES]
    grid = plan.final_grid
    outcomes, seconds = _simulate(run, sim, [design for _, design in designs], grid)
    round_number = max(t.round for t in trials) + 1
    # Numbered by finalist order for now, so equal final scores keep the search's own ranking; renumbered when stored.
    rows = [
        _trial_row(run, grid, i, round_number, key, design, by_pose, sec, final=True)
        for i, ((key, design), by_pose, sec) in enumerate(zip(designs, outcomes, seconds, strict=True))
    ]
    order = _ranked(rows[: len(finalists)])
    for rank, row in enumerate(order, 1):
        row.label = f"D{rank}"
    for row in rows[len(finalists) :]:
        row.label = BASELINE_LABELS[row.kind]
    winner = order[0]
    design = Design(kind=winner.kind, params=winner.params)
    pose = grasp_pose_for(job, run.gripper, design)
    export = _export(run, cad, design, pose, outputs_dir)
    meta = _run_meta(run, sim, trials, started)
    with db.session() as s:
        s.execute(delete(TrialRow).where(TrialRow.job_id == job.id, TrialRow.grid == "final"))
        first = (s.scalar(select(func.max(TrialRow.number)).where(TrialRow.job_id == job.id)) or 0) + 1
        for i, row in enumerate(rows):
            row.number = first + i
        s.add_all(rows)
        s.merge(
            ResultRow(
                job_id=job.id,
                label="D1",
                trial_number=winner.number,
                search=winner.search,
                kind=winner.kind,
                params=winner.params,
                grasp_pose=pose,
                predicted_success=winner.success_rate,
                capture_radius_mm=winner.capture_radius_mm,
                cad_files={key: str(path) for key, path in export.files.items()},
                checks=[check.model_dump() for check in export.checks],
                created=time.time(),
            )
        )
        s.merge(RunMetaRow(job_id=job.id, meta=meta))
        s.flush()
        n_done = s.scalar(select(func.count()).select_from(TrialRow).where(TrialRow.job_id == job.id))
        values = {"n_done": n_done, "round": round_number + 1, "n_rounds": round_number + 1, "finished": time.time()}
        values |= {"status": "done", "best_value": winner.success_rate, "best_trial": winner.number}
        s.execute(update(JobRow).where(JobRow.id == job.id).values(**values))
    logger.info("Job %s: D1 %.3f (stock %.3f)", job.id, winner.success_rate, next(r.success_rate for r in rows if r.label == "STOCK"))


def _ranked(trials: list) -> list:
    """Best first: target score, then capture radius (None: not even the centre held), then the earlier design."""
    return sorted(trials, key=lambda t: (-t.success_rate, -(t.capture_radius_mm if t.capture_radius_mm is not None else -1.0), t.number))


def _export(run: _Run, cad: CadClient, design: Design, pose: dict, outputs_dir: Path) -> FingerExport:
    """D1's printable files and checks. An export that fails outright doesn't fail the job: the results stand, and the
    failure is a blocking check, so the downloads say why."""
    job = run.job
    try:
        return cad.export(
            job.part,
            design,
            run.gripper,
            finger_id=finger_id(job.experiment_id, "D1"),
            stem=outputs_dir / job.id / file_stem(job.name, job.experiment_id, "D1", job.sim_backend),
            sheet=print_sheet(run.profile, job, "D1", design, pose),
        )
    except Exception as e:
        logger.exception("Job %s: exporting D1 failed", job.id)
        return FingerExport(files={}, checks=[ExportCheck(name="export", ok=False, blocking=True, detail=f"the CAD export failed: {e}")])


def _run_meta(run: _Run, sim: SimClient, trials: list[Trial], started: float) -> dict:
    """What the run used, for whoever repeats or audits it. Built after the final batch, so the sim server's
    describe() reports what it ran with."""
    job, plan, cell = run.job, run.job.plan, run.profile.profile
    described = sim.describe()
    searches = []
    for search in plan.searches:
        mine = [t for t in trials if t.search == search.key]
        searches.append(
            {
                "key": search.key,
                "family": search.family,
                "method": search.method,
                "budget": search.budget,
                "batch_size": search.batch_size,
                "patience": search.patience,
                "designs": len(mine),
                "rounds": len({t.round for t in mine}),
                "best": max((t.success_rate for t in mine), default=None),
                "stop_reason": _stop_reason(search, mine) or "budget",
            }
        )
    return {
        "job_id": job.id,
        "experiment_id": job.experiment_id,
        "name": job.name,
        "created": job.created,
        "finished": time.time(),
        "runtime_s": time.time() - started,  # this worker's; a resumed job's earlier workers aren't counted
        "versions": {
            "python": platform.python_version(),
            "botorch": botorch.__version__,
            "gpytorch": gpytorch.__version__,
            "torch": torch.__version__,
            "cadquery": cadquery.__version__,
        },
        "gpu": _gpu_name(),
        "cpus": os.cpu_count(),
        "seed": job.spec.seed,
        "grids": {"search": plan.grid.model_dump(), "final": plan.final_grid.model_dump()},
        "sim": {"backend": sim.backend, "badge": job.sim_backend, "url": sim.url, "describe": described},
        "cell_profile": {"id": run.profile.id, "name": run.profile.name, "version": run.profile.version},
        "grip_force_n": plan.grip_force_n,
        "poses": [
            {"key": p.key, "label": p.label, "probability": p.probability, "weight": p.weight, "grasp": p.grasp.model_dump(mode="json")}
            for p in job.poses
        ],
        "searches": searches,
        "warnings": cell.sim.differences(described) + [f"cell profile vs the sim: {m}" for m in cell.twin_mismatches()],
        "spec": job.spec.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
    }


def _load_trials(db: DatabaseClient, job_id: str, grid: str) -> list[Trial]:
    with db.session() as s:
        rows = s.scalars(select(TrialRow).where(TrialRow.job_id == job_id, TrialRow.grid == grid).order_by(TrialRow.number))
        return [Trial.model_validate(row) for row in rows]


def _next_number(db: DatabaseClient, job_id: str) -> int:
    with db.session() as s:
        last = s.scalar(select(func.max(TrialRow.number)).where(TrialRow.job_id == job_id))
    return 0 if last is None else last + 1


def _cancelled(db: DatabaseClient, job_id: str) -> bool:
    """Whether a cancel was asked for; if so, marks the job cancelled (the rounds done so far stay, for a resume)."""
    with db.session() as s:
        if not s.scalar(select(JobRow.cancel_requested).where(JobRow.id == job_id)):
            return False
    update_job(db, job_id, status="cancelled")
    logger.info("Job %s: cancelled", job_id)
    return True


def _failure(error: Exception) -> tuple[str, int | None]:
    """The job card's one line for a failure, and the input step that fixes it when that's known."""
    if isinstance(error, JobRunError):
        return error.line, error.step
    if isinstance(error, SimError):
        return f"sim: {error}", None
    text = next((line.strip() for line in str(error).splitlines() if line.strip()), "")
    line = f"{type(error).__name__}: {text}" if text else type(error).__name__
    return line[:300], None


def _gpu_name() -> str | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None
