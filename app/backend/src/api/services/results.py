"""An experiment's results (outputs spec; plan 4.7): the results page, re-scored on request, and each final design's
files, grasp pose and 3D preview.

Everything is computed from the stored trials' raw outcomes, so a re-score at another error model or task (POST
/api/jobs/{id}/rescore) stores and simulates nothing. Design labels were fixed by the final test; a re-score changes the
numbers next to them, and the summary names the design that leads at the new settings.

Printable files are built on demand per design and cached under outputs/<job id>/<label>/; D1's were written when the
job finished. The CAD export runs in the API process (the routers call it in a thread), never in a database session.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from api.clients.cad import CadClient
from api.clients.database import DatabaseClient
from api.db.tables import ResultRow, RunMetaRow, TrialRow
from api.models.cell_profile import CellProfileVersion, Gripper
from api.models.design import Design
from api.models.error_model import CURVE_SIGMAS_MM, PRESETS, ErrorModel
from api.models.export_check import ExportCheck
from api.models.finger import build_finger, stock_finger, stock_grasp_pose
from api.models.job import Job, JobResult, Trial
from api.models.offset_grid import OffsetGrid
from api.models.print_sheet import PrintSheet
from api.models.printed_finger import finger_id
from api.models.results import (
    FILE_SUFFIXES,
    BestFinger,
    Curve,
    Curves,
    DesignExport,
    DesignScore,
    FailureView,
    FinalRow,
    FingerPreview,
    HeldMap,
    InHandView,
    MapPoint,
    ResultsHeader,
    ResultsSummary,
    ResultsView,
    RunDetails,
    SearchProgress,
    file_stem,
    grasp_pose_text,
    mirrored,
    misses,
    task_metric,
    task_metric_label,
)
from api.models.task import Task, offset_mm
from api.services import cell_profiles, parts, physical_trials
from api.services.jobs import get_job

logger = logging.getLogger(__name__)

EXPORT_MANIFEST = "export.json"


class ResultsNotReadyError(RuntimeError):
    """The job hasn't run its final test yet, so there are no labelled designs."""


class DesignNotFoundError(LookupError):
    """No final design has this label, or it has no such file."""


class DesignNotExportableError(ValueError):
    """The design can't be printed: the stock fingers are already on the robot."""


class ExportBlockedError(RuntimeError):
    """A blocking export check failed, so the files must not be downloaded. checks: the failed ones."""

    def __init__(self, label: str, checks: list[ExportCheck]):
        self.checks = checks
        super().__init__(f"{label} can't be downloaded: " + "; ".join(f"{c.name}: {c.detail}" for c in checks))


@dataclass(frozen=True)
class _Scored:
    """A trial scored at the view's error model and task."""

    trial: Trial
    success: list[bool]
    rate: float
    radius: float | None
    metric: float | None

    def score(self) -> DesignScore:
        t = self.trial
        return DesignScore(
            label=t.label, kind=t.kind, search=t.search, success=self.rate, capture_radius_mm=self.radius, task_metric=self.metric
        )


def results(db: DatabaseClient, job_id: str, *, error: ErrorModel | None = None, task: Task | None = None) -> ResultsView:
    """The results view, at the job's own error model and task, or at the ones given (a re-score)."""
    job = get_job(db, job_id)
    with db.session() as s:
        trials = [
            Trial.model_validate(row) for row in s.scalars(select(TrialRow).where(TrialRow.job_id == job_id).order_by(TrialRow.number))
        ]
        result_row, meta_row = s.get(ResultRow, job_id), s.get(RunMetaRow, job_id)
        result = JobResult.model_validate(result_row) if result_row else None
        meta = dict(meta_row.meta) if meta_row else {}
    error, task = error or job.spec.error, task or job.spec.task
    grid = job.plan.final_grid
    weights = grid.weights(error)
    final = sorted(
        (_score(t, grid, error, task, weights) for t in trials if t.grid == "final"), key=lambda sc: _label_order(sc.trial.label)
    )
    by_label = {sc.trial.label: sc for sc in final}
    best = by_label.get("D1")
    searched = [t for t in trials if t.grid == "search"]
    return ResultsView(
        header=_header(db, job, error, task),
        summary=_summary(final, best, by_label, searched, task) if best else None,
        curves=_curves(final, grid, error) if final else None,
        held_maps=[_held_map(by_label[label], grid, weights) for label in ("D1", "STOCK") if label in by_label],
        in_hand=_in_hand(best, task, weights) if best else None,
        failures=_failures(best, grid, weights, job, error, task, trials) if best else None,
        best_finger=_best_finger(result) if result else None,
        final_table=[
            FinalRow(
                label=sc.trial.label,
                kind=sc.trial.kind,
                search=sc.trial.search,
                params=sc.trial.params,
                success=sc.rate,
                capture_radius_mm=sc.radius,
                task_metric=sc.metric,
                print_selected=sc.trial.label in job.print_designs,
            )
            for sc in final
        ],
        physical=physical_trials.validation(db, job_id),
        run=_run_details(job, searched, meta, error, task),
    )


def _score(trial: Trial, grid: OffsetGrid, error: ErrorModel, task: Task, weights: list[float]) -> _Scored:
    outcomes = trial.outcomes()
    success = task.success(outcomes)
    return _Scored(
        trial, success, grid.expected_success(success, error), grid.capture_radius(success), task_metric(outcomes, task, weights)
    )


def _label_order(label: str | None) -> tuple[int, int]:
    """D1, D2, ..., then STOCK, then IMP."""
    if label and label.startswith("D") and label[1:].isdigit():
        return 0, int(label[1:])
    return (1, 0) if label == "STOCK" else (2, 0)


def _header(db: DatabaseClient, job: Job, error: ErrorModel, task: Task) -> ResultsHeader:
    try:
        profile = cell_profiles.get_profile(db, job.cell_profile_id)
    except cell_profiles.CellProfileNotFoundError:
        profile = None
    try:
        part_name = parts.get_part(db, job.part_id).name
    except parts.PartNotFoundError:
        part_name = None
    return ResultsHeader(
        job_id=job.id,
        name=job.name,
        experiment_id=job.experiment_id,
        status=job.status,
        sim_backend=job.sim_backend,
        cell_profile_name=profile.name if profile else None,
        cell_profile_version=profile.version if profile else None,
        part_name=part_name,
        task=task,
        error=error,
        rescored=error != job.spec.error or task != job.spec.task,
        created=job.created,
        finished=job.finished,
    )


def _summary(final: list[_Scored], best: _Scored, by_label: dict[str, _Scored], searched: list[Trial], task: Task) -> ResultsSummary:
    stock, imprint = by_label.get("STOCK"), by_label.get("IMP")
    designs = [sc for sc in final if sc.trial.kind not in ("stock", "imprint")]
    leader = min(designs, key=lambda sc: (-sc.rate, -(sc.radius if sc.radius is not None else -1.0), _label_order(sc.trial.label)))
    return ResultsSummary(
        best=best.score(),
        stock=stock.score() if stock else None,
        imprint=imprint.score() if imprint else None,
        leader=leader.trial.label,
        gain_vs_stock=best.rate - stock.rate if stock else None,
        gain_vs_imprint=best.rate - imprint.rate if imprint else None,
        designs_evaluated=sum(1 for t in searched if t.kind in ("search", "locked")),
        task_metric_label=task_metric_label(task),
    )


def _curves(final: list[_Scored], grid: OffsetGrid, error: ErrorModel) -> Curves:
    return Curves(
        sigmas_mm=list(CURVE_SIGMAS_MM),
        target_sigma_mm=error.sigma_mm,
        target_range_mm=error.sigma_range_mm,
        designs=[Curve(label=sc.trial.label, kind=sc.trial.kind, success=grid.curve(sc.success, error)) for sc in final],
    )


def _held_map(scored: _Scored, grid: OffsetGrid, weights: list[float]) -> HeldMap:
    points = [
        MapPoint(dx=p["dx"], dy=p["dy"], yaw_deg=p["yaw_deg"], weight=w, held=held, success=ok)
        for p, w, held, ok in zip(grid.points(), weights, scored.trial.held, scored.success, strict=True)
    ]
    return HeldMap(label=scored.trial.label, points=points)


def _in_hand(best: _Scored, task: Task, weights: list[float]) -> InHandView:
    held = [(pose, w) for pose, w, h in zip(best.trial.in_hand, weights, best.trial.held, strict=True) if h and pose is not None]
    return InHandView(
        label=best.trial.label,
        n_held=sum(best.trial.held),
        offsets_mm=[offset_mm(pose) for pose, _ in held],
        tilts_deg=[pose[3] for pose, _ in held],
        weights=[w for _, w in held],
        offset_tolerance_mm=task.offset_tolerance_mm,
        tilt_tolerance_deg=task.tilt_tolerance_deg,
        within_tolerance=best.metric,
    )


def _failures(
    best: _Scored, grid: OffsetGrid, weights: list[float], job: Job, error: ErrorModel, task: Task, trials: list[Trial]
) -> FailureView:
    centre_missed, by_direction, by_distance = misses(grid, best.success, weights)
    nearest = [g.nearest_miss_mm for g in by_direction if g.nearest_miss_mm is not None]
    first = 0.0 if centre_missed else min(nearest, default=None)
    return FailureView(
        label=best.trial.label,
        centre_missed=centre_missed,
        first_miss_mm=first,
        by_direction=by_direction,
        by_distance=by_distance,
        caveats=caveats(job, error, task, trials),
    )


def caveats(job: Job, error: ErrorModel, task: Task, trials: list[Trial]) -> list[str]:
    """What every number on the page assumes and isn't yet checked against the real cell."""
    out = []
    if job.sim_backend == "mock":
        out.append("mock sim: geometry only, no physics, so these success rates are not predictions")
    else:
        out.append("rigid-body physics: no compliance, wear or deformation of the part or the printed pads")
    static, dynamic = job.part.friction
    out.append(
        f"friction is an estimate ({static:g} static, {dynamic:g} sliding against the printed pad, from the material table): "
        "measure it with a tilt test"
    )
    preset = PRESETS.get(error.preset)
    if preset is not None and preset.placeholder:
        out.append(f"the '{preset.label}' camera error ({error.sigma_mm:g} mm) is a placeholder until it's measured on the cell")
    if task.transport and not any(t.held_after_transport is not None for t in trials):
        out.append("this run didn't simulate a transport move, so holding through one isn't checked")
    if job.part.shape == "mesh":
        out.append(f"the part is simulated as {len(job.part.pieces)} convex pieces, an approximation of its shape")
    return out


def _best_finger(result: JobResult) -> BestFinger:
    blocked = [c for c in result.checks if c.blocking and not c.ok]
    return BestFinger(
        label=result.label,
        kind=result.kind,
        search=result.search,
        params=result.params,
        grasp_pose=result.grasp_pose,
        grasp_pose_text=grasp_pose_text(result.grasp_pose),
        files=[key for key in FILE_SUFFIXES if key in result.cad_files],
        checks=result.checks,
        download_blocked=bool(blocked) or not result.cad_files,
    )


def _run_details(job: Job, searched: list[Trial], meta: dict, error: ErrorModel, task: Task) -> RunDetails:
    """Each search's progress (best so far at these settings against designs evaluated) and what the run used."""
    grid = job.plan.grid
    weights = grid.weights(error)
    stopped = {s.get("key"): s.get("stop_reason") for s in meta.get("searches", [])}
    progress = []
    for search in job.plan.searches:
        mine = sorted((t for t in searched if t.search == search.key), key=lambda t: t.number)
        best_so_far, best = [], None
        for t in mine:
            rate = _score(t, grid, error, task, weights).rate
            best = rate if best is None else max(best, rate)
            best_so_far.append(best)
        reason = stopped.get(search.key) or search.stop_reason([t.success_rate for t in mine])
        progress.append(
            SearchProgress(
                key=search.key,
                family=search.family,
                method=search.method,
                budget=search.budget,
                n_initial=search.n_initial,
                batch_size=search.batch_size,
                patience=search.patience,
                designs_evaluated=len(mine),
                rounds=len({t.round for t in mine}),
                best=best,
                best_so_far=best_so_far,
                stop_reason=reason,
            )
        )
    return RunDetails(
        searches=progress,
        rounds=job.round,
        n_rounds=job.n_rounds,
        error=job.spec.error,
        task=job.spec.task,
        seed=job.spec.seed,
        grids={"search": job.plan.grid.model_dump(), "final": job.plan.final_grid.model_dump()},
        versions=meta.get("versions", {}),
        gpu=meta.get("gpu"),
        sim=meta.get("sim", {}),
        runtime_s=meta.get("runtime_s"),
        warnings=meta.get("warnings", []),
    )


def run_metadata(db: DatabaseClient, job_id: str) -> dict:
    """What the run used (versions, GPU, grids, seed, sim, cell profile, plan, stop reasons), written when it finished."""
    get_job(db, job_id)
    with db.session() as s:
        row = s.get(RunMetaRow, job_id)
        if row is None:
            raise ResultsNotReadyError(f"job {job_id} hasn't finished, so it has no run metadata yet")
        return dict(row.meta)


def design_export(db: DatabaseClient, job_id: str, label: str, *, cad: CadClient, outputs_dir: Path) -> DesignExport:
    """A final design's printable files and their checks: D1's as written when the job finished, any other's exported
    now and cached under outputs/<job id>/<label>/. The files exist even when a blocking check failed; design_file()
    refuses them then. The stock fingers can't be exported."""
    job, trial = final_trial(db, job_id, label)
    label = trial.label
    if trial.kind == "stock":
        raise DesignNotExportableError("the stock fingers are aluminium and already on the robot: there's nothing to print")
    if label == "D1":
        with db.session() as s:
            row = s.get(ResultRow, job_id)
            stored = JobResult.model_validate(row) if row else None
        if stored and stored.cad_files and all(Path(p).exists() for p in stored.cad_files.values()):
            return DesignExport(label=label, files=stored.cad_files, checks=stored.checks)
    folder = outputs_dir / job_id / label
    manifest = folder / EXPORT_MANIFEST
    if manifest.exists():
        cached = DesignExport.model_validate_json(manifest.read_text(encoding="utf-8"))
        if cached.files and all(Path(p).exists() for p in cached.files.values()):
            return cached
    profile = cell_profiles.get_profile(db, job.cell_profile_id)
    gripper = profile.profile.gripper
    design = Design(kind=trial.kind, params=trial.params)
    pose = grasp_pose_for(job, gripper, design)
    try:
        export = cad.export(
            job.part,
            design,
            gripper,
            finger_id=finger_id(job.experiment_id, label),
            stem=folder / file_stem(job.name, job.experiment_id, label, job.sim_backend),
            sheet=print_sheet(profile, job, label, design, pose),
        )
    except Exception as e:  # CadQuery raises its own types; the download then says why instead of failing outright
        logger.exception("Job %s: exporting %s failed", job_id, label)
        return DesignExport(
            label=label, files={}, checks=[ExportCheck(name="export", ok=False, blocking=True, detail=f"the CAD export failed: {e}")]
        )
    result = DesignExport(label=label, files={key: str(path) for key, path in export.files.items()}, checks=export.checks)
    manifest.write_text(result.model_dump_json(), encoding="utf-8")
    return result


def design_file(db: DatabaseClient, job_id: str, label: str, key: str, *, cad: CadClient, outputs_dir: Path) -> tuple[Path, str]:
    """One printable file of a final design ("step", "stl_left", "stl_right" or "print_sheet") and the name to download
    it as (<slug(name)>_<EXP-id>_<label>[_MOCK]...). Raises ExportBlockedError when a blocking check failed."""
    export = design_export(db, job_id, label, cad=cad, outputs_dir=outputs_dir)
    if export.blocked:
        raise ExportBlockedError(export.label, export.blocked)
    path = export.files.get(key)
    if path is None or key not in FILE_SUFFIXES:
        raise DesignNotFoundError(f"{export.label} has no {key} file")
    job = get_job(db, job_id)
    return Path(path), file_stem(job.name, job.experiment_id, export.label, job.sim_backend) + FILE_SUFFIXES[key]


def grasp_pose(db: DatabaseClient, job_id: str, label: str) -> dict:
    """The grasp to give the robot with a final design: D1's as stored, any other's worked out from its finger."""
    job, trial = final_trial(db, job_id, label)
    if trial.label == "D1":
        with db.session() as s:
            row = s.get(ResultRow, job_id)
            if row is not None:
                return dict(row.grasp_pose)
    gripper = cell_profiles.get_profile(db, job.cell_profile_id).profile.gripper
    return grasp_pose_for(job, gripper, Design(kind=trial.kind, params=trial.params))


def grasp_pose_for(job: Job, gripper: Gripper, design: Design) -> dict:
    """A design's finger settings (approach, fingertip height, jaw positions, TCP) plus the grasp axis and centre chosen
    in step 5, in the table frame of the chosen resting pose."""
    pose = stock_grasp_pose(job.part, gripper) if design.kind == "stock" else build_finger(job.part, design, gripper).grasp_pose
    grasp = job.spec.grasp
    return {
        **pose,
        "grasp_angle_deg": grasp.angle_deg,
        "grasp_centre_mm": list(grasp.centre_mm),
        "frame": "table frame of the chosen resting pose: the jaws close along grasp_angle_deg, centred on grasp_centre_mm",
    }


def finger_preview(db: DatabaseClient, job_id: str, label: str = "D1") -> FingerPreview:
    """Both fingers of a final design (the stock ones are the mock's stand-in) and the part, for the 3D preview."""
    job, trial = final_trial(db, job_id, label)
    gripper = cell_profiles.get_profile(db, job.cell_profile_id).profile.gripper
    design = Design(kind=trial.kind, params=trial.params)
    finger = stock_finger(job.part, gripper) if design.kind == "stock" else build_finger(job.part, design, gripper)
    return FingerPreview(
        label=trial.label,
        part=job.part,
        extent_mm=job.part.extent_mm,
        jaw_open_mm=gripper.stroke_mm,
        finger=finger,
        right=mirrored(finger.pieces),
    )


def print_sheet(profile: CellProfileVersion, job: Job, label: str, design: Design, pose: dict) -> PrintSheet:
    """The print sheet for one of the job's designs: what to print it in, and what's still to confirm before it's
    bolted on."""
    cell = profile.profile
    caveats = [
        f"{field.replace('_', ' ')}: a placeholder in cell profile {profile.name!r} until confirmed at the cell"
        for field in cell.to_confirm
    ]
    if "finger_mount" in cell.to_confirm:
        caveats.insert(0, f"finger mount ({cell.finger_mount.describe()}): confirm it on the real jaw before printing")
    if job.sim_backend == "mock":
        caveats.insert(0, "MOCK sim: geometry only, no physics; this design's success rate is not a prediction")
    return PrintSheet(
        experiment=f"{job.name} ({job.experiment_id})",
        finger_id=finger_id(job.experiment_id, label),
        design_label=label,
        params=None if design.params is None else design.params.model_dump(),
        material=cell.pad_material,
        pad_friction=cell.pad_friction,
        sim_backend=job.sim_backend,
        grasp_pose=pose,
        caveats=caveats,
    )


def final_trial(db: DatabaseClient, job_id: str, label: str) -> tuple[Job, Trial]:
    """The job and its final-grid trial with this label (any case)."""
    job = get_job(db, job_id)
    wanted = label.strip().upper()
    with db.session() as s:
        rows = list(s.scalars(select(TrialRow).where(TrialRow.job_id == job_id, TrialRow.grid == "final")))
        trials = [Trial.model_validate(row) for row in rows]
    if not trials:
        raise ResultsNotReadyError(f"{job.experiment_id} hasn't run its final test yet, so its designs aren't labelled")
    for trial in trials:
        if trial.label == wanted:
            return job, trial
    labels = ", ".join(t.label for t in sorted(trials, key=lambda t: _label_order(t.label)))
    raise DesignNotFoundError(f"{job.experiment_id} has no design {label!r}; its final designs are {labels}")
