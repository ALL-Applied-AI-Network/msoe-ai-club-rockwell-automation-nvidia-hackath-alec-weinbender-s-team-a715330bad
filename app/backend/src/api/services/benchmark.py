"""Budget-matched BO, Sobol and genetic experiments, separate from production jobs."""

import hashlib
import json
import random
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from api.clients.cad import CadClient
from api.clients.database import DatabaseClient
from api.clients.sim import SimClient
from api.config import AppConfig
from api.models.benchmark import BenchmarkConfig, Observation
from api.models.design import Design
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.offset_grid import OffsetGrid
from api.services import cell_profiles, jobs, optimizer, parts

METHODS = ("bo", "sobol", "ga")
ASSETS = {
    "cube": "manipbench-cube-10mm.step",
    "cube16": "manipbench-cube-16mm.step",
    "screw": "ISO10642-M6x30-countersunk-screw.step",
}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def prepare(config: BenchmarkConfig, app: AppConfig, db: DatabaseClient, cad: CadClient, root: Path):
    """Resolve one pose/grasp through the app's existing CAD and planning services."""
    db.migrate()
    cell_profiles.ensure_default_profile(db)
    profile = cell_profiles.list_profiles(db)[0]
    asset = root / "cad" / ASSETS[config.case]
    content = asset.read_bytes()
    record = parts.create_part(db, app, cad, asset.name, content, "mm")
    pose = 0
    if config.case == "screw":
        poses = parts.resting_poses(db, record.id)
        stable = [index for index, candidate in enumerate(poses) if candidate.source == "stable"]
        if not stable:
            raise ValueError("screw has no stable resting pose")
        pose = min(stable, key=lambda index: (poses[index].extent_mm[2], index))
    changes = {"material": "steel" if config.case == "screw" else "pla", "pose": pose}
    if config.case == "screw":
        changes["mass_g"] = 7.5
    record = parts.update_part(db, record.id, changes)
    if config.case != "screw":
        candidate = parts.check_grasp(db, record.id, profile.profile, angle_deg=0)
    else:
        candidates = parts.propose_grasps(db, record.id, profile.profile).candidates
        candidate = next((candidate for candidate in candidates if candidate.verdict != "blocked"), None)
    if candidate is None or candidate.verdict == "blocked":
        raise ValueError("no valid grasp for the configured pose")
    spec = JobSpec(
        name="Benchmark preparation",
        part_id=record.id,
        cell_profile_id=profile.id,
        grasp=GraspChoice(angle_deg=candidate.angle_deg, centre_mm=candidate.centre_mm, span_mm=candidate.span_mm),
        budget=config.budget,
    )
    job = jobs.create_job(db, app, spec, start=False)
    run = optimizer._load(db, job)
    if len(run.job.poses) != 1 or len(run.job.plan.searches) != 1 or not run.spaces[run.job.plan.searches[0].key].names:
        raise ValueError("benchmark requires one resting pose and one nonempty search space")
    if config.pilot:
        plan = run.job.plan
        plan.grid = OffsetGrid(radii_mm=[4.0], n_directions=2, yaws_deg=[0.0])
        plan.final_grid = plan.grid.model_copy(deep=True)
        plan.totals.search_offsets = plan.grid.size
        plan.totals.final_offsets = plan.final_grid.size
        plan.totals.search_grasps = plan.totals.search_designs * plan.grid.size
        plan.totals.final_grasps = plan.totals.final_designs * plan.final_grid.size
        plan.totals.total_grasps = plan.totals.search_grasps + plan.totals.final_grasps
        plan.estimate.seconds = None
        plan.warnings.append("PILOT: center and +/-4 mm at yaw zero only; scores are diagnostic, not full-grid accuracy estimates")
    metadata = {
        "asset": str(asset.relative_to(root)),
        "asset_sha256": hashlib.sha256(content).hexdigest(),
        "part_record": record.model_dump(mode="json"),
        "grasp": candidate.model_dump(mode="json"),
        "spec": job.spec.model_dump(mode="json"),
        "plan": job.plan.model_dump(mode="json"),
        "cell_profile": profile.model_dump(mode="json"),
    }
    return run, metadata


def schedule(run, config: BenchmarkConfig) -> list[int]:
    search = run.job.plan.searches[0]
    dimensions = len(run.spaces[search.key].names)
    initial = min(2 * dimensions + 4, config.budget)
    batch_size = search.batch_size if search.method == "bo" else max(1, min(4, (config.budget - initial) // 4))
    counts = [initial]
    while sum(counts) < config.budget:
        counts.append(min(batch_size, config.budget - sum(counts)))
    return counts


def estimate(run, config: BenchmarkConfig) -> dict:
    search_grid, final_grid = run.job.plan.grid.size, run.job.plan.final_grid.size
    search = 3 * config.budget * search_grid + 2 * search_grid
    final = ((3 * min(3, config.budget) + 2) * config.selection_repeats + 3 * 5) * final_grid
    total = len(config.seeds) * (search + final)
    return {
        "batch_schedule": schedule(run, config),
        "methods": list(METHODS),
        "grid_kind": "pilot diagnostic" if config.pilot else "standard",
        "search_offsets": search_grid,
        "final_offsets": final_grid,
        "candidate_evaluations": len(config.seeds) * 3 * config.budget,
        "maximum_simulator_grasps": total,
        "estimated_simulator_seconds": total / config.reference_grasps_per_s,
        "estimate_note": "Assumed throughput; excludes proposal/CAD time; rejected geometry costs no simulator grasps.",
    }


def genetic(space, history: list[Observation], count: int, population_size: int, rng: random.Random) -> list[list[float]]:
    """Elitist steady-state population with seeded tournament/crossover/mutation."""
    population = sorted(history, key=lambda observation: (-observation.success_rate, observation.number))[:population_size]
    dimensions = len(space.names)

    def parent():
        winner = min(rng.choices(population, k=3), key=lambda observation: (-observation.success_rate, observation.number))
        return space.to_unit(winner.design)

    children = []
    for _ in range(count):
        first, second = parent(), parent()
        child = []
        for first_value, second_value in zip(first, second, strict=True):
            value = first_value if rng.random() < 0.5 else second_value
            if rng.random() < 1 / dimensions:
                value += rng.gauss(0, 0.1)
            child.append(min(1.0, max(0.0, value)))
        children.append(child)
    return children


def unique_finalists(history: list[Observation], count: int = 3) -> list[Observation]:
    """Reserve validation slots for distinct, buildable collision geometry."""
    kept, seen = [], set()
    for row in optimizer._ranked(history):
        if row.geometry_hash is None or row.geometry_hash in seen:
            continue
        kept.append(row)
        seen.add(row.geometry_hash)
        if len(kept) == count:
            break
    if not kept:
        raise ValueError("search produced no buildable finalist geometry")
    return kept


def select_winner(rows: list[Observation]) -> tuple[Observation, dict]:
    """Rank candidate means on repeated selection grids; holdout repeats remain independent."""
    grouped: dict[str, list[Observation]] = {}
    for row in rows:
        grouped.setdefault(row.parameter_hash, []).append(row)
    summaries = []
    for observations in grouped.values():
        scores = [row.success_rate for row in observations]
        radii = [row.capture_radius_mm for row in observations]
        summaries.append(
            (
                observations[0],
                {
                    "mean": statistics.mean(scores),
                    "sd": statistics.stdev(scores) if len(scores) > 1 else None,
                    "repeats": len(scores),
                    "minimum_capture_radius_mm": None if None in radii else min(radii),
                },
            )
        )
    if not summaries:
        raise ValueError("no finalist selection observations")
    return min(
        summaries,
        key=lambda item: (
            -item[1]["mean"],
            -(item[1]["minimum_capture_radius_mm"] if item[1]["minimum_capture_radius_mm"] is not None else -1),
            item[0].number,
        ),
    )


def evaluate(run, sim, designs, grid, *, seed, method, phase, batch, earlier, proposal_s=0.0, source="validation", fallback_reason=None):
    if len(run.job.poses) != 1:
        raise ValueError("benchmark v1 evaluates one resting pose")
    details = []
    outcomes, seconds = optimizer._simulate(run, sim, designs, grid, diagnostics=details)
    rows = []
    parameter_hashes = {row.parameter_hash for row in earlier}
    geometry_hashes = {row.geometry_hash for row in earlier if row.geometry_hash is not None}
    cumulative = sum(row.grasps for row in earlier)
    for design, by_pose, duration, detail in zip(designs, outcomes, seconds, details, strict=True):
        outcome = by_pose[0]
        success = run.job.spec.task.success(outcome)
        parameter_hash = fingerprint(design.model_dump(mode="json"))
        geometry_hash = None if detail["rejections"] else fingerprint({"finger": detail["finger"], "settings": run.settings.model_dump()})
        grasps = detail["simulated_grasps"]
        cumulative += grasps
        rows.append(
            Observation(
                seed=seed,
                method=method,
                phase=phase,
                number=len(earlier) + len(rows),
                batch=batch,
                design=design,
                success_rate=grid.expected_success(success, run.job.spec.error),
                capture_radius_mm=grid.capture_radius(success),
                outcomes=outcome,
                grasps=grasps,
                measured_grasps=sum(measurement is not None for measurement in outcome.landing) if outcome.landing is not None else None,
                cumulative_grasps=cumulative,
                proposal_s=proposal_s / len(designs),
                geometry_s=detail["geometry_s"],
                simulator_s=duration,
                source=source,
                fallback_reason=fallback_reason,
                rejections=detail["rejections"],
                parameter_hash=parameter_hash,
                geometry_hash=geometry_hash,
                duplicate_parameters=parameter_hash in parameter_hashes,
                duplicate_geometry=geometry_hash in geometry_hashes,
            )
        )
        parameter_hashes.add(parameter_hash)
        if geometry_hash is not None:
            geometry_hashes.add(geometry_hash)
    return rows


def execute(run, config: BenchmarkConfig, sim: SimClient, state: dict, checkpoint: Callable[[], None]) -> None:
    """Checkpoint each completed batch. Exceptions propagate to the runner's failure manifest."""
    search = run.job.plan.searches[0]
    space = run.spaces[search.key]
    counts = schedule(run, config)
    production = search.model_copy(update={"method": "bo", "n_initial": counts[0]})

    def save(rows):
        state["observations"].extend(row.model_dump(mode="json") for row in rows)
        checkpoint()

    for seed in config.seeds:
        baselines = [Design(kind=kind) for kind in ("stock", "imprint")]
        save(evaluate(run, sim, baselines, run.job.plan.grid, seed=seed, method="baseline", phase="search", batch=0, earlier=[]))
        winners = []
        offset = seed % len(METHODS)
        order = METHODS[offset:] + METHODS[:offset]
        for method in order:
            started = time.perf_counter()
            history = []
            rng = random.Random(seed)
            patience_at = None
            for batch, count in enumerate(counts):
                proposal_started = time.perf_counter()
                diagnostics = {"source": "sobol_initial" if batch == 0 else method}
                if batch == 0 or method == "sobol":
                    points = optimizer._sobol(len(space.names), count, seed, skip=len(history))
                elif method == "bo":
                    points = optimizer._propose(space, history, count, seed=seed, round_number=batch, diagnostics=diagnostics)
                else:
                    points = genetic(space, history, count, counts[0], rng)
                rows = evaluate(
                    run,
                    sim,
                    [space.from_unit(point) for point in points],
                    run.job.plan.grid,
                    seed=seed,
                    method=method,
                    phase="search",
                    batch=batch,
                    earlier=history,
                    proposal_s=time.perf_counter() - proposal_started,
                    **diagnostics,
                )
                history.extend(rows)
                if patience_at is None and production.stop_reason([row.success_rate for row in history]) == "patience":
                    patience_at = len(history)
                save(rows)
            finalists = unique_finalists(history)
            dense = []
            for repeat in range(config.selection_repeats):
                selected = evaluate(
                    run,
                    sim,
                    [row.design for row in finalists],
                    run.job.plan.final_grid,
                    seed=seed,
                    method=method,
                    phase="final",
                    batch=repeat,
                    earlier=dense,
                )
                dense.extend(selected)
                save(selected)
            winner, selection = select_winner(dense)
            winners.append((method, winner.design))
            state["searches"].append(
                {
                    "seed": seed,
                    "method": method,
                    "wall_s": time.perf_counter() - started,
                    "patience_would_stop_at": patience_at,
                    "winner": winner.model_dump(mode="json"),
                    "selection": selection,
                    "unique_finalists": len(finalists),
                }
            )
            checkpoint()
        baseline_dense = []
        for repeat in range(config.selection_repeats):
            selected = evaluate(
                run,
                sim,
                baselines,
                run.job.plan.final_grid,
                seed=seed,
                method="baseline",
                phase="final",
                batch=repeat,
                earlier=baseline_dense,
            )
            baseline_dense.extend(selected)
            save(selected)
        for repeat in range(3):
            for method, design in winners + list(zip(("stock", "imprint"), baselines, strict=True)):
                save(
                    evaluate(
                        run, sim, [design], run.job.plan.final_grid, seed=seed, method=method, phase="repeat", batch=repeat, earlier=[]
                    )
                )
