"""Runs one job: batch Bayesian optimisation of the finger design in the simulator, then re-validation of the best.

Every design is scored the same way: tried at every point of a fixed grid of camera errors (api/models/offset_grid.py)
and scored by its expected success under the job's error model. A round is one batch, one sim request. Round 0 is the
stock and imprint baselines plus a Sobol sample of the search space; every later round fits a GP to all scores so far
and picks the next batch with BoTorch's qLogNoisyExpectedImprovement. Each round is checkpointed to the database, so a
crashed or cancelled job resumes at the next round. Finally the best designs and the baselines are re-tested together
on a denser grid, and the winner's validated score is the predicted success we report.
"""

import logging
import os
import platform
import subprocess
import time
import traceback
from pathlib import Path

import botorch
import torch
from botorch.acquisition.logei import qLogNoisyExpectedImprovement
from botorch.fit import fit_gpytorch_mll
from botorch.models import SingleTaskGP
from botorch.models.transforms.outcome import Standardize
from botorch.optim import optimize_acqf
from gpytorch.mlls import ExactMarginalLogLikelihood
from sqlalchemy import select
from torch.quasirandom import SobolEngine

from api.clients.cad import CadClient
from api.clients.database import DatabaseClient
from api.clients.sim import SimClient
from api.db.tables import JobRow, ResultRow, RunMetaRow, TrialRow
from api.models.design import Design, DesignKind
from api.models.finger import build_finger, problems
from api.models.job import JobConfig
from api.models.offset_grid import OffsetGrid
from api.models.part import Part
from api.models.search_space import SearchSpace
from api.services.jobs import JobNotFoundError, get_job, update_job

logger = logging.getLogger(__name__)

BASELINES: tuple[DesignKind, ...] = ("stock", "imprint")
FINALISTS = 3  # top designs re-tested on the denser grid
CURVE_SIGMAS_MM = (0.5, 1, 2, 3, 4, 5)  # error levels the result reports success at
MIN_GAIN = 0.005  # a round only counts as an improvement if it beats the best score by this much


def run_job(db: DatabaseClient, job_id: str, *, sim: SimClient, cad: CadClient, outputs_dir: Path) -> None:
    """Run or resume a job to completion. A failure is stored on the job (status 'failed' + traceback), not raised."""
    started = time.time()
    try:
        job = get_job(db, job_id)
    except JobNotFoundError:
        logger.error("Job %s: not found", job_id)
        return
    update_job(db, job_id, status="running", pid=os.getpid(), error=None, cancel_requested=0)
    logger.info("Job %s: running (sim=%s)", job_id, sim.backend)
    try:
        space, grid = SearchSpace(job.part), OffsetGrid.for_part(job.part, job.config.sigma_deg)
        if not _optimize(db, job_id, job.part, job.config, space, grid, sim):
            logger.info("Job %s: cancelled", job_id)
            return
        _finalize(db, job_id, job.part, job.config, space, grid, sim=sim, cad=cad, outputs_dir=outputs_dir, started=started)
        logger.info("Job %s: done in %.0f s", job_id, time.time() - started)
    except Exception:
        logger.exception("Job %s: failed", job_id)
        update_job(db, job_id, status="failed", error=traceback.format_exc()[-2000:])


def _optimize(db: DatabaseClient, job_id: str, part: Part, cfg: JobConfig, space: SearchSpace, grid: OffsetGrid, sim: SimClient) -> bool:
    """Stage 1: rounds until the budget is spent or `patience` rounds pass without improvement. False if cancelled."""
    update_job(db, job_id, stage="optimize", n_total=cfg.budget + len(BASELINES))
    trials = _load_trials(db, job_id)
    while True:
        searched = [t for t in trials if t.kind == "search"]
        if len(searched) >= cfg.budget or _stale_rounds(trials) >= cfg.patience:
            return True
        with db.session() as s:
            if s.scalar(select(JobRow.cancel_requested).where(JobRow.id == job_id)):
                update_job(db, job_id, status="cancelled", stage=None)
                return False
        number = trials[-1].round + 1 if trials else 0
        q = min(cfg.batch_size, cfg.budget - len(searched))
        designs = [Design(kind=kind) for kind in BASELINES] if number == 0 else []
        designs += [space.from_unit(u) for u in _propose(space, searched, q, seed=cfg.seed + number)]
        _run_round(db, job_id, part, cfg, grid, sim, number, designs, first=len(trials))
        trials = _load_trials(db, job_id)
        best = max(t.success_rate for t in trials if t.kind == "search")
        logger.info("Job %s: round %d done, %d designs, best %.3f", job_id, number, len(trials), best)
        update_job(db, job_id, n_done=len(trials), best_value=best)


def _propose(space: SearchSpace, searched: list[TrialRow], q: int, seed: int) -> list[list[float]]:
    """The next q points of the unit cube. A Sobol sample to start (and if fitting fails); after that, the batch that
    BoTorch expects to improve most on the best score so far, chosen one point at a time with the earlier ones treated
    as pending, so the batch spreads out instead of piling onto one optimum."""
    d = len(space.names)
    if len(searched) < 2:
        return SobolEngine(d, scramble=True, seed=seed).draw(q, dtype=torch.double).tolist()
    torch.manual_seed(seed)
    x = torch.tensor([space.to_unit(Design(params=t.params)) for t in searched], dtype=torch.double)
    y = torch.tensor([[t.success_rate] for t in searched], dtype=torch.double)
    try:
        model = SingleTaskGP(x, y, outcome_transform=Standardize(m=1))
        fit_gpytorch_mll(ExactMarginalLogLikelihood(model.likelihood, model))
        acquisition = qLogNoisyExpectedImprovement(model, X_baseline=x, prune_baseline=True)
        bounds = torch.stack([torch.zeros(d, dtype=torch.double), torch.ones(d, dtype=torch.double)])
        candidates, _ = optimize_acqf(acquisition, bounds=bounds, q=q, num_restarts=8, raw_samples=256, sequential=True)
        return candidates.tolist()
    except Exception:
        logger.warning("GP proposal failed; using a Sobol sample this round", exc_info=True)
        return SobolEngine(d, scramble=True, seed=seed).draw(q, dtype=torch.double).tolist()


def _run_round(
    db: DatabaseClient,
    job_id: str,
    part: Part,
    cfg: JobConfig,
    grid: OffsetGrid,
    sim: SimClient,
    number: int,
    designs: list[Design],
    *,
    first: int,
) -> None:
    """Simulate one batch and store it in one transaction: a round is checkpointed whole or not at all."""
    started = time.time()
    results = _simulate(part, designs, grid, sim)
    duration = (time.time() - started) / len(designs)
    with db.session() as s:
        for i, (design, (held, _)) in enumerate(zip(designs, results, strict=True)):
            s.add(
                TrialRow(
                    job_id=job_id,
                    number=first + i,
                    round=number,
                    kind=design.kind,
                    params=design.params,
                    success_rate=grid.expected_success(held, cfg.sigma_mm, cfg.sigma_deg),
                    capture_radius_mm=grid.capture_radius(held),
                    n_grasps=len(held),
                    n_success=sum(held),
                    held=held,
                    duration=duration,
                )
            )


def _simulate(part: Part, designs: list[Design], grid: OffsetGrid, sim: SimClient) -> list[tuple[list[bool], list[str]]]:
    """Every design at every grid point, in one sim request: (held per point, problems) per design. A design that fails
    the geometry checks isn't sent; it counts as failing every grasp."""
    fingers, issues = [], []
    for design in designs:
        finger = None if design.kind == "stock" else build_finger(part, design)
        fingers.append(finger)
        issues.append([] if finger is None else problems(part, finger))
        if issues[-1]:
            logger.info("Not simulating a %s design (%s): %s", design.kind, design.params, "; ".join(issues[-1]))
    runnable = [finger for finger, found in zip(fingers, issues, strict=True) if not found]
    rows = iter(sim.run_batch(part, runnable, grid.points()) if runnable else [])
    n = len(grid.points())
    return [([False] * n if found else next(rows), found) for found in issues]


def _finalize(
    db: DatabaseClient,
    job_id: str,
    part: Part,
    cfg: JobConfig,
    space: SearchSpace,
    grid: OffsetGrid,
    *,
    sim: SimClient,
    cad: CadClient,
    outputs_dir: Path,
    started: float,
) -> None:
    """Stage 2: re-test the finalists and both baselines together on a denser grid, so the winner isn't just the design
    that happened to suit the search grid, and the comparison is like for like. Store the winner and its CAD file."""
    update_job(db, job_id, stage="finalize")
    trials = _load_trials(db, job_id)
    finalists = sorted((t for t in trials if t.kind == "search"), key=lambda t: (-t.success_rate, t.number))[:FINALISTS]
    if not finalists:
        raise RuntimeError("the search produced no designs")
    fine = grid.refined()
    designs = [Design(params=t.params) for t in finalists] + [Design(kind=kind) for kind in BASELINES]
    results = _simulate(part, designs, fine, sim)
    scores = [fine.expected_success(held, cfg.sigma_mm, cfg.sigma_deg) for held, _ in results]
    k = max(range(len(finalists)), key=lambda i: scores[i])
    winner = finalists[k]

    def entry(i: int) -> dict:
        held, found = results[i]
        name = "optimized" if i == k else f"#{finalists[i].number}" if i < len(finalists) else designs[i].kind
        return {
            "name": name,
            "kind": designs[i].kind,
            "trial_number": finalists[i].number if i < len(finalists) else None,
            "success": scores[i],
            "capture_radius_mm": fine.capture_radius(held),
            "curve": {f"{sigma:g}": fine.expected_success(held, sigma, cfg.sigma_deg) for sigma in CURVE_SIGMAS_MM},
            "problems": found,
        }

    order = [k, *range(len(finalists), len(designs)), *(i for i in range(len(finalists)) if i != k)]
    finger = build_finger(part, designs[k])
    outputs_dir.mkdir(parents=True, exist_ok=True)
    cad_path = outputs_dir / f"{job_id}{cad.extension}"
    cad_path.write_text(cad.export(finger, label=f"job {job_id}: trial #{winner.number}, {_describe(designs[k].params)}"))
    meta = {
        "started": started,
        "runtime_s": time.time() - started,
        "config": cfg.model_dump(),
        "part": part.model_dump(),
        "space": {"names": space.names, "bounds": space.bounds()},
        "grid": grid.model_dump(),
        "validation_grid": fine.model_dump(),
        "sim_backend": sim.backend,
        "sim_url": sim.url,
        "botorch": botorch.__version__,
        "torch": torch.__version__,
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
        "gpu": _gpu_name(),
        "n_trials": len(trials),
        "n_rounds": trials[-1].round + 1,
    }
    with db.session() as s:
        s.merge(
            ResultRow(
                job_id=job_id,
                trial_number=winner.number,
                kind="search",
                params=winner.params,
                grasp_pose=finger.grasp_pose,
                predicted_success=scores[k],
                capture_radius_mm=fine.capture_radius(results[k][0]),
                comparison=[entry(i) for i in order],
                scad_path=str(cad_path),
            )
        )
        s.merge(RunMetaRow(job_id=job_id, meta=meta))
    update_job(db, job_id, status="done", stage=None, best_value=scores[k], best_trial=winner.number, finished=time.time())


def _load_trials(db: DatabaseClient, job_id: str) -> list[TrialRow]:
    with db.session() as s:
        return list(s.scalars(select(TrialRow).where(TrialRow.job_id == job_id).order_by(TrialRow.number)))


def _stale_rounds(trials: list[TrialRow]) -> int:
    """Rounds since the best search score last improved."""
    best, stale = None, 0
    for number in sorted({t.round for t in trials}):
        top = max((t.success_rate for t in trials if t.round == number and t.kind == "search"), default=None)
        if top is None:
            continue
        if best is None or top > best + MIN_GAIN:
            best, stale = top, 0
        else:
            stale += 1
    return stale


def _describe(params: dict[str, float]) -> str:
    return ", ".join(f"{name} {value:.1f}" for name, value in params.items())


def _gpu_name() -> str | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None
