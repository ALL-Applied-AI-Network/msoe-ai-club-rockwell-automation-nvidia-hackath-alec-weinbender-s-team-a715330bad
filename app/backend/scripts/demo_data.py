"""Demo data for building and showing the UI. From the repo root:

    uv run --package backend python app/backend/scripts/demo_data.py [--data-dir DIR] [--reset] [--live]

A script, not part of the api package: it only uses the package's services, the way the API's routes do. It fills its
OWN data directory (default app/data/demo, gitignored; never the app's real one) with parts, cell profiles,
experiments in every state, and the results tracker's printed fingers, test plans and logged physical trials. Then run
the API on it with DEMO_DATA=true. That's all a user needs to do: on its first start with DEMO_DATA=true, the API runs this
script itself, in the background, and the experiments appear as they finish (about two minutes).

The experiments are real runs of the pipeline (upload, resting pose, grasp proposal, plan, optimizer, final test, CAD
export) on the mock sim, so they carry the Mock badge: geometry only, never predictions. The physical trials are made up,
since no robot was involved: each says so in its operator and notes fields, and they only ever exist in the demo's own
database. Experiment names start with "[DEMO]".

What's created:
- parts: the vial cap, a 10 mm cube, a lying glass tube (fragile), an aluminium L-bracket (a mesh part, uploaded as an
  STL), and a steel plate lying flat (nothing fits it: the grasp step's "nothing fits" screen);
- cell profiles: the UWM CSI cell, and a hypothetical long-stroke cell with two versions (switching profiles);
- done experiments across the tasks (drop, place with a biased camera and a sigma range, insert), a "test my own
  design" run, a mesh part, a fragile part and one on the long-stroke cell; one cancelled, one interrupted (resumable)
  and one failed;
- for two of them, a print selection, printed fingers and a predicted test plan: one fully logged (validated), one
  half logged (in progress);
- with --live, one more experiment run by a real worker process, so the job list shows queued and running live.
"""

import argparse
import csv
import io
import logging
import math
import shutil
import sys
import tempfile
from collections.abc import Callable
from contextlib import closing
from datetime import date
from pathlib import Path

import cadquery as cq
import numpy as np
from pydantic import SecretStr

from api.clients.cad import CadClient, create_cad_client
from api.clients.database import DatabaseClient
from api.clients.sim import MockSim, SimError
from api.config import APP_DIR, AppConfig, DbConfig, SimConfig, setup_logging
from api.models.cell_profile import DEFAULT_PROFILE
from api.models.error_model import ErrorModel
from api.models.family import FamilyChoice, ParamRange
from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec
from api.models.task import Task
from api.services import cell_profiles, jobs, optimizer, parts, physical_trials, printed_fingers, reviews, test_plans

logger = logging.getLogger(__name__)

DEFAULT_DIR = APP_DIR / "data" / "demo"
PREFIX = "[DEMO] "
OPERATOR = "demo seed (made up, not measured)"
NOTE = "DEMO DATA: a made-up outcome for the UI, not a measurement"
SEED = 2026
LONG_STROKE = "[DEMO] Long-stroke cell (hypothetical)"

SHAPES: dict[str, Callable[[], cq.Workplane]] = {
    "vial-cap": lambda: cq.Workplane("XY").circle(15.875).extrude(15.7).faces(">Z").workplane().hole(28.0, 13.7),
    "cube-10mm": lambda: cq.Workplane("XY").box(10, 10, 10),
    "glass-tube": lambda: cq.Workplane("YZ").circle(8.5).extrude(140),
    "l-bracket": lambda: cq.Workplane("XY").polyline([(0, 0), (30, 0), (30, 6), (6, 6), (6, 20), (0, 20)]).close().extrude(12),
    "steel-plate": lambda: cq.Workplane("XY").box(120, 120, 4),
}


class _WorkerDied(BaseException):
    """Stands in for a worker process that was killed mid-run (BaseException, so run_job doesn't record it as a failure)."""


class _StoppingSim(MockSim):
    """The mock, which after `after` batches either requests a cancel (as the UI's cancel button does) or dies."""

    def __init__(self, after: int, then: Callable[[], None]):
        self.after, self.then, self.batches = after, then, 0

    def run_batch(self, part, fingers, offsets, settings):
        self.batches += 1
        if self.batches > self.after:
            self.then()
        return super().run_batch(part, fingers, offsets, settings)


class _UnreachableSim(MockSim):
    def run_batch(self, part, fingers, offsets, settings):
        raise SimError("can't reach the sim server at http://localhost:9000/evaluate_batch (connection refused)")


def seed(config: AppConfig, *, live: bool = False) -> list[str]:
    """Create the demo data in config's (empty) database. Returns the experiment ids."""
    db = DatabaseClient(config.db)
    db.migrate()
    cell_profiles.ensure_default_profile(db)
    with closing(db), closing(create_cad_client()) as cad:
        uwm = cell_profiles.list_profiles(db)[0]
        long_stroke = _long_stroke_profile(db)
        ids = {name: _part(db, config, cad, name) for name in SHAPES}
        cap, cube, tube, bracket = ids["vial-cap"], ids["cube-10mm"], ids["glass-tube"], ids["l-bracket"]
        _material(db, cap, "pla", "standing on an end")
        _material(db, cube, "abs", "standing")
        _material(db, tube, "glass", "lying on its side", fragile=True, max_grip_force_n=8.0)
        _material(db, bracket, "aluminium", "lying flat")
        _material(db, ids["steel-plate"], "steel", "lying flat")

        made = []

        def run(name: str, part_id: str, profile_id: int, **spec) -> str:
            job = jobs.create_job(db, config, _spec(db, name, part_id, profile_id, **spec), start=False)
            optimizer.run_job(db, job.id, sim=MockSim(), cad=cad, outputs_dir=config.outputs_dir)
            made.append(job.id)
            return job.id

        drop = run("Vial cap - pick and drop", cap, uwm.id, budget=40)
        place = run(
            "Vial cap - pick and place, biased camera",
            cap,
            uwm.id,
            task=Task(kind="place", offset_tolerance_mm=1.5, transport="normal"),
            error=ErrorModel(preset="custom", sigma_mm=2.0, sigma_range_mm=(0.5, 5.0), sigma_deg=8.0, bias_mm=1.0, bias_direction_deg=90),
            families=[FamilyChoice(ranges={"slack_mm": ParamRange(lo=0.5, hi=3.0)})],
            budget=40,
        )
        run(
            "10 mm cube - pick and insert",
            cube,
            uwm.id,
            task=Task(kind="insert", offset_tolerance_mm=1.0, tilt_tolerance_deg=5.0),
            error=ErrorModel.from_preset("calibrated"),
            budget=32,
        )
        run(
            "10 mm cube - test my own design",
            cube,
            uwm.id,
            families=[FamilyChoice(locks={"pad_width_mm": 10.0, "slack_mm": 1.0, "tip_height_mm": 2.0, "lead_in_mm": 1.0})],
        )
        run("Glass tube (fragile) - pick and drop, cheap camera", tube, uwm.id, error=ErrorModel.from_preset("cheap"), budget=30)
        run("L-bracket (mesh part) - pick and drop", bracket, uwm.id, budget=30)
        run("Vial cap - long-stroke cell", cap, long_stroke, budget=24)
        made += _unfinished(db, config, cad, cap, uwm.id)

        _tracker(db, config, drop, logged=1.0, approved=True)
        _tracker(db, config, place, logged=0.55, approved=False)
        if live:
            job = jobs.create_job(db, config, _spec(db, "Vial cap - live run (watch it go)", cap, uwm.id), start=True)
            made.append(job.id)
        return made


def _long_stroke_profile(db: DatabaseClient) -> int:
    """A made-up second cell, to show switching profiles: a longer stroke and more room beside the gripper. The sim still
    models the twin's SMC gripper, so its jobs carry twin-mismatch warnings. Saved twice, to show versions."""
    profile = DEFAULT_PROFILE.model_copy(
        update={
            "gripper_model": "SCHUNK JGP 64 (hypothetical)",
            "stroke_per_jaw_mm": 10.0,
            "grip_force_n": 40.0,
            "air_pressure_mpa": 0.6,
            "free_space_mm": (55.0, 35.0),
            "to_confirm": [*DEFAULT_PROFILE.to_confirm, "stroke_per_jaw_mm", "air_pressure_mpa"],
        }
    )
    first = cell_profiles.create_profile(db, LONG_STROKE, profile)
    return cell_profiles.update_profile(db, first.id, profile.model_copy(update={"hole_clearance_mm": 0.3})).id


def _part(db: DatabaseClient, config: AppConfig, cad: CadClient, name: str) -> str:
    """Upload a generated part the way a user would: STEP for most, STL (in mm) for the bracket."""
    suffix = ".stl" if name == "l-bracket" else ".step"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{name}{suffix}"
        shape = SHAPES[name]()
        if suffix == ".stl":
            cq.exporters.export(shape.val(), str(path), tolerance=0.01, angularTolerance=0.1)
        else:
            cq.exporters.export(shape, str(path))
        record = parts.create_part(db, config, cad, path.name, path.read_bytes(), "mm" if suffix == ".stl" else None)
    return record.id


def _material(db: DatabaseClient, part_id: str, material: str, pose_label: str, **changes) -> None:
    poses = parts.resting_poses(db, part_id)
    pose = next((i for i, pose in enumerate(poses) if pose.label == pose_label), 0)
    parts.update_part(db, part_id, {"material": material, "pose": pose, **changes})


def _spec(db: DatabaseClient, name: str, part_id: str, profile_id: int, **values) -> JobSpec:
    """A spec with the part's best proposed grasp on this cell, as the wizard would accept it."""
    profile = cell_profiles.get_profile(db, profile_id).profile
    best = parts.propose_grasps(db, part_id, profile).candidates[0]
    grasp = GraspChoice(angle_deg=best.angle_deg, centre_mm=best.centre_mm)
    return JobSpec(name=PREFIX + name, part_id=part_id, cell_profile_id=profile_id, grasp=grasp, seed=SEED, **values)


def _unfinished(db: DatabaseClient, config: AppConfig, cad: CadClient, part_id: str, profile_id: int) -> list[str]:
    """A cancelled run, an interrupted one (its worker died; resumable) and a failed one (the sim was unreachable)."""
    cancelled = jobs.create_job(db, config, _spec(db, "Vial cap - cancelled", part_id, profile_id, budget=40), start=False)
    sim = _StoppingSim(after=1, then=lambda: jobs.cancel_job(db, cancelled.id))
    optimizer.run_job(db, cancelled.id, sim=sim, cad=cad, outputs_dir=config.outputs_dir)

    interrupted = jobs.create_job(db, config, _spec(db, "Vial cap - interrupted (resumable)", part_id, profile_id, budget=40), start=False)

    def die() -> None:
        raise _WorkerDied

    try:
        optimizer.run_job(db, interrupted.id, sim=_StoppingSim(after=2, then=die), cad=cad, outputs_dir=config.outputs_dir)
    except _WorkerDied:
        jobs.update_job(db, interrupted.id, status="interrupted", pid=None)  # what the API's startup finds and marks

    failed = jobs.create_job(db, config, _spec(db, "Vial cap - sim server down", part_id, profile_id, budget=40), start=False)
    optimizer.run_job(db, failed.id, sim=_UnreachableSim(), cad=cad, outputs_dir=config.outputs_dir)
    return [cancelled.id, interrupted.id, failed.id]


def _tracker(db: DatabaseClient, config: AppConfig, job_id: str, *, logged: float, approved: bool) -> None:
    """Print D1 and D2 (and the imprint), plan their physical test, predict it on the mock, and log made-up outcomes for
    `logged` of the planned trials."""
    reviews.set_review(
        db,
        job_id,
        status="approved" if approved else "pending",
        reviewer="Demo reviewer" if approved else "",
        notes="DEMO DATA: not a real review",
    )
    printed_fingers.set_print_selection(db, job_id, ["D1", "D2"])
    for label in ("D1", "D2", "IMP"):
        printed_fingers.add_printed_finger(db, job_id, design_label=label, material="PLA", print_date=date.today(), notes=NOTE)
    plan = test_plans.create_test_plan(db, config, job_id, seed=SEED, start=False)
    test_plans.predict_test_plan(db, plan.id, sim=MockSim())
    _, content = test_plans.plan_csv(db, job_id, plan.id, include_predicted=True)
    task = jobs.get_job(db, job_id).spec.task
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    rng = np.random.default_rng(SEED)
    for row in rows:
        if rng.random() >= logged:
            continue
        held = _made_up_held(row["predicted"] == "yes", float(row["offset_x_mm"]), float(row["offset_y_mm"]), rng)
        row["outcome"] = "held" if held else "missed"
        if task.kind in ("place", "insert") and held:
            row["in_tolerance"] = "yes" if rng.random() < 0.85 else "no"
        row["operator"], row["notes"] = OPERATOR, NOTE
    for row in rows:
        row["predicted"] = ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    report = physical_trials.upload_results(db, job_id, plan.id, "demo-outcomes.csv", out.getvalue().encode())
    if report.errors:
        logger.warning("Demo outcomes for job %s: %d rows rejected, e.g. %s", job_id, len(report.errors), report.errors[0].reason)


def _made_up_held(predicted: bool, dx: float, dy: float, rng: np.random.Generator) -> bool:
    """Agree with the sim most of the time, and be a little less forgiving than it further out, so the validation views
    show agreement, both kinds of mismatch and a gap that grows with the offset."""
    r = math.hypot(dx, dy)
    return bool(rng.random() < (max(0.5, 0.95 - 0.04 * r) if predicted else 0.08))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="demo_data.py", description="Fill a separate data directory with demo data for the UI")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIR, help=f"where the demo database and files go (default {DEFAULT_DIR})")
    parser.add_argument("--reset", action="store_true", help="delete that directory first (stop the API first)")
    parser.add_argument("--live", action="store_true", help="also start one experiment in a real worker process, to watch it run")
    args = parser.parse_args(argv)
    setup_logging("INFO")
    data_dir = args.data_dir.resolve()
    if args.reset and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    # Its own SQLite file and the mock sim, whatever DB_URL, SIM_BACKEND and DEMO_DATA say: demo data never reaches a real
    # database, and a run on the mock must carry the Mock badge.
    config = AppConfig(
        data_dir=data_dir,
        demo_data=False,
        db=DbConfig(url=SecretStr(f"sqlite:///{(data_dir / 'app.db').as_posix()}")),
        sim=SimConfig(backend="mock"),
    )
    if _has_data(config):
        sys.exit(f"{data_dir} already has parts or experiments; pass --reset to start it over")
    made = seed(config, live=args.live)
    logger.info("Demo data: %d experiments in %s. Run the API on it with DEMO_DATA=true (see .env.example).", len(made), data_dir)


def _has_data(config: AppConfig) -> bool:
    """Whether the database already holds parts or experiments. An empty one (the API creates and migrates it on its first
    start with DEMO_DATA=true, then starts this script) is fine to fill."""
    db = DatabaseClient(config.db)
    with closing(db):
        db.migrate()
        return bool(parts.list_parts(db) or jobs.list_jobs(db))


if __name__ == "__main__":
    main()
