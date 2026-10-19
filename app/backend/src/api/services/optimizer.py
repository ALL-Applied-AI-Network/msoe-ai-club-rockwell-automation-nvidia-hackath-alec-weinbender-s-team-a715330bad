"""Runs one job: LLM proposals, parallel Bayesian optimisation in the simulator, then re-validation of the best designs.

Candidates are evaluated in parallel across CPU cores, hopeless ones are pruned early, and every trial is checkpointed to
the database, so a crashed or cancelled job resumes without losing work. Each write is its own short session, so the
API sees progress as it happens.
"""

import logging
import math
import os
import platform
import random
import subprocess
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import optuna
from sqlalchemy import func, select

from api.clients.cad import CadClient
from api.clients.database import DatabaseClient
from api.clients.llm import PROMPT_VERSION, LlmClient
from api.clients.sim import SimClient
from api.db.tables import JobRow, ResultRow, RunMetaRow, SuggestionRow, TrialRow
from api.models.design import SPACE, TEMPLATES, Design, clamp_params
from api.models.job import JobConfig
from api.models.part import Part
from api.services.jobs import JobNotFoundError, get_job, update_job

logger = logging.getLogger(__name__)
optuna.logging.set_verbosity(optuna.logging.WARNING)

GRASP_CHUNK = 10  # grasps per sim batch; pruning is checked between batches


def run_job(db: DatabaseClient, job_id: str, *, llm: LlmClient, sim: SimClient, cad: CadClient, outputs_dir: Path) -> None:
    """Run or resume a job to completion. A failure is stored on the job (status 'failed' + traceback), not raised."""
    started = time.time()
    try:
        job = get_job(db, job_id)
    except JobNotFoundError:
        logger.error("Job %s: not found", job_id)
        return
    update_job(db, job_id, status="running", pid=os.getpid(), error=None, cancel_requested=0)
    logger.info("Job %s: running (llm=%s, sim=%s)", job_id, llm.backend, sim.backend)
    try:
        _store_suggestions(db, job_id, job.part, job.task, job.config, llm)
        progress = _optimize(db, job_id, job.part, job.config, sim)
        if progress is None:
            logger.info("Job %s: cancelled", job_id)
            return
        n_trials, workers = progress
        _finalize(
            db, job_id, job.part, job.config, n_trials=n_trials, workers=workers, started=started, sim=sim, cad=cad, outputs_dir=outputs_dir
        )
        logger.info("Job %s: done in %.0f s", job_id, time.time() - started)
    except Exception:
        logger.exception("Job %s: failed", job_id)
        update_job(db, job_id, status="failed", error=traceback.format_exc()[-2000:])


def _store_suggestions(db: DatabaseClient, job_id: str, part: Part, task: str, cfg: JobConfig, llm: LlmClient) -> None:
    """Stage 1: LLM proposals, stored verbatim for later training. Skipped on resume."""
    with db.session() as s:
        if s.scalar(select(SuggestionRow.id).where(SuggestionRow.job_id == job_id).limit(1)) is not None:
            return
    update_job(db, job_id, stage="llm")
    reply = llm.suggest(part, task, cfg.n_suggestions)  # outside any session: the LLM can take a while
    with db.session() as s:
        for i, suggestion in enumerate(reply.suggestions):
            template = suggestion["template"] if suggestion["template"] in SPACE else "flat_pad"
            s.add(
                SuggestionRow(
                    job_id=job_id,
                    idx=i,
                    template=template,
                    params=clamp_params(template, suggestion.get("params", {})),
                    rationale=suggestion.get("rationale", ""),
                    source=reply.source,
                    model=reply.model,
                    raw_response=reply.raw,
                )
            )


def _optimize(db: DatabaseClient, job_id: str, part: Part, cfg: JobConfig, sim: SimClient) -> tuple[int, int] | None:
    """Stage 2: Bayesian optimisation (ask/tell, parallel, resumable). Returns (trials run, pool size), or None if cancelled."""
    update_job(db, job_id, stage="optimize", n_total=cfg.budget)
    sampler = optuna.samplers.TPESampler(multivariate=True, group=True, seed=cfg.seed, n_startup_trials=max(cfg.n_suggestions, 8))
    study = optuna.create_study(direction="maximize", sampler=sampler)
    with db.session() as s:
        done = s.scalars(select(TrialRow).where(TrialRow.job_id == job_id).order_by(TrialRow.number)).all()
        untried = s.scalars(
            select(SuggestionRow).where(SuggestionRow.job_id == job_id, SuggestionRow.trial_number.is_(None)).order_by(SuggestionRow.idx)
        ).all()
    for t in done:  # replay the checkpoint
        study.add_trial(
            optuna.trial.create_trial(params=_flat(t.template, t.params), distributions=_distributions(t.template), value=t.success_rate)
        )
    for suggestion in untried:
        study.enqueue_trial(_flat(suggestion.template, suggestion.params))
    number = len(done)
    best_rate = max([t.success_rate for t in done if not t.pruned], default=None)
    stale = 0
    workers = cfg.workers or max(1, (os.cpu_count() or 2) - 1)

    with ProcessPoolExecutor(workers) as pool:
        while number < cfg.budget and stale < cfg.patience:
            with db.session() as s:
                cancel_requested = s.scalar(select(JobRow.cancel_requested).where(JobRow.id == job_id))
            if cancel_requested:
                update_job(db, job_id, status="cancelled", stage=None)
                return None
            batch = []
            for _ in range(min(workers, cfg.budget - number)):
                trial = study.ask()
                template = trial.suggest_categorical("template", TEMPLATES)
                params = {name: trial.suggest_float(f"{template}.{name}", lo, hi) for name, (lo, hi) in SPACE[template].items()}
                batch.append((trial, template, params))
            futures = {
                pool.submit(evaluate_design, sim, part, Design(template=template, params=params), cfg, best_rate): (trial, template, params)
                for trial, template, params in batch
            }
            for future in as_completed(futures):
                trial, template, params = futures[future]
                r = future.result()
                study.tell(trial, r["rate"])
                with db.session() as s:
                    s.add(
                        TrialRow(
                            job_id=job_id,
                            number=number,
                            template=template,
                            params=params,
                            success_rate=r["rate"],
                            n_grasps=r["n_grasps"],
                            n_success=r["n_success"],
                            pruned=int(r["pruned"]),
                            suggestion_id=_link_suggestion(s, job_id, template, params, number),
                            duration=r["duration"],
                        )
                    )
                number += 1
                if not r["pruned"] and (best_rate is None or r["rate"] > best_rate + 0.005):
                    best_rate, stale = r["rate"], 0
                else:
                    stale += 1
                update_job(db, job_id, n_done=number, best_value=best_rate)
    return number, workers


def _finalize(
    db: DatabaseClient,
    job_id: str,
    part: Part,
    cfg: JobConfig,
    *,
    n_trials: int,
    workers: int,
    started: float,
    sim: SimClient,
    cad: CadClient,
    outputs_dir: Path,
) -> None:
    """Stage 3: re-validate the top 3 on fresh perturbations (new seed, 3x grasps) to avoid winner's-curse bias, then
    store the winner. The validated rate is what we report as the predicted success rate."""
    update_job(db, job_id, stage="finalize")
    with db.session() as s:
        top = s.scalars(
            select(TrialRow)
            .where(TrialRow.job_id == job_id, TrialRow.pruned == 0)
            .order_by(TrialRow.success_rate.desc(), TrialRow.number)
            .limit(3)
        ).all()
        first_suggestion = s.scalars(select(SuggestionRow).where(SuggestionRow.job_id == job_id).limit(1)).first()
        n_pruned = s.scalar(select(func.count()).select_from(TrialRow).where(TrialRow.job_id == job_id, TrialRow.pruned == 1))
    designs = [Design(template=t.template, params=t.params) for t in top]
    validation_cfg = cfg.model_copy(update={"seed": cfg.seed + 1, "n_grasps": cfg.n_grasps * 3, "prune": False})
    n = len(top)
    with ProcessPoolExecutor(min(3, workers)) as pool:
        validated = list(pool.map(evaluate_design, [sim] * n, [part] * n, designs, [validation_cfg] * n, [None] * n))
    k = max(range(n), key=lambda i: validated[i]["rate"])
    winner, v, design = top[k], validated[k], designs[k]
    lo, hi = wilson(v["n_success"], v["n_grasps"])

    outputs_dir.mkdir(parents=True, exist_ok=True)
    cad_path = outputs_dir / f"{job_id}{cad.extension}"
    cad_path.write_text(cad.export(part, design))
    llm_source = {"source": first_suggestion.source, "model": first_suggestion.model} if first_suggestion else {}
    meta = {
        "started": started,
        "runtime_s": time.time() - started,
        "config": cfg.model_dump(),
        "part": part.model_dump(),
        "llm": {"backend": llm_source, "prompt_version": PROMPT_VERSION},
        "sim_backend": sim.backend,
        "sim_url": sim.url,
        "optuna": optuna.__version__,
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
        "gpu": _gpu_name(),
        "n_trials": n_trials,
        "n_pruned": n_pruned,
    }
    with db.session() as s:
        s.merge(
            ResultRow(
                job_id=job_id,
                trial_number=winner.number,
                template=winner.template,
                params=winner.params,
                grasp_pose=grasp_pose(part, design),
                predicted_success=v["rate"],
                ci_low=lo,
                ci_high=hi,
                scad_path=str(cad_path),
            )
        )
        s.merge(RunMetaRow(job_id=job_id, meta=meta))
    update_job(db, job_id, status="done", stage=None, best_value=v["rate"], best_trial=winner.number, finished=time.time())


def evaluate_design(sim: SimClient, part: Part, design: Design, cfg: JobConfig, best_rate: float | None) -> dict:
    """Runs in a pool process. Repeated grasps with camera-error offsets, in chunks, stopping early once the Wilson upper
    bound can't beat the current best (multi-fidelity pruning)."""
    started = time.time()
    n, successes, done, pruned = cfg.n_grasps, 0, 0, False
    while done < n:
        end = min(n, done + GRASP_CHUNK)
        offsets = [camera_offset(i, cfg.sigma_mm, cfg.sigma_deg, cfg.seed) for i in range(done, end)]
        successes += sum(sim.run_grasps(part, design, offsets))
        done = end
        if cfg.prune and best_rate is not None and 20 <= done < n and wilson(successes, done)[1] < best_rate - 0.02:
            pruned = True
            break
    return {"n_grasps": done, "n_success": successes, "rate": successes / done, "pruned": pruned, "duration": time.time() - started}


def camera_offset(i: int, sigma_mm: float, sigma_deg: float, seed: int) -> dict:
    """The i-th grasp's perturbation. Deterministic, so every design faces the same 'camera errors' (common random
    numbers: a fairer, lower-variance comparison)."""
    r = random.Random(seed * 100003 + i)
    return {"dx": r.gauss(0, sigma_mm), "dy": r.gauss(0, sigma_mm), "yaw_deg": r.gauss(0, sigma_deg)}


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a success rate."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0, center - half), min(1, center + half)


def grasp_pose(part: Part, design: Design) -> dict:
    length = design.params["finger_length"]
    return {
        "frame": "part_centroid",
        "approach_axis": "-Z",
        "standoff_mm": round(length * 0.5, 1),
        "tcp_offset_mm": [0, 0, round(length, 1)],
        "gripper_opening_mm": round(part.diameter_mm + 6, 1),
    }


def _link_suggestion(s, job_id: str, template: str, params: dict, number: int) -> int | None:
    """If this trial evaluated an enqueued LLM suggestion, link the two and return the suggestion id."""
    untried = s.scalars(select(SuggestionRow).where(SuggestionRow.job_id == job_id, SuggestionRow.trial_number.is_(None)))
    for suggestion in untried:
        if suggestion.template == template and all(abs(suggestion.params[k] - v) < 1e-9 for k, v in params.items()):
            suggestion.trial_number = number
            return suggestion.id
    return None


def _distributions(template: str) -> dict:
    return {
        "template": optuna.distributions.CategoricalDistribution(TEMPLATES),
        **{f"{template}.{name}": optuna.distributions.FloatDistribution(lo, hi) for name, (lo, hi) in SPACE[template].items()},
    }


def _flat(template: str, params: dict) -> dict:
    return {"template": template, **{f"{template}.{name}": v for name, v in clamp_params(template, params).items()}}


def _gpu_name() -> str | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None
