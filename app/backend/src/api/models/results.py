"""What the outputs show for an experiment: its card in the job list, its results page, and the files it exports.

Everything here is computed from stored raw outcomes (api/models/outcome.py), never stored itself: the results page can
re-score a finished job at another error model or task without simulating again (POST /api/jobs/{id}/rescore). Design
labels (D1, D2, ..., STOCK, IMP) are fixed when the final test runs, since printed fingers carry them; a re-score
changes the numbers next to them, not the labels.

Offsets and in-hand poses are in the gripper frame at the grasp: x along the jaws' closing direction, y across it.
"""

import math
import re
from typing import Any

from pydantic import BaseModel

from api.models.design import DesignKind
from api.models.error_model import ErrorModel
from api.models.export_check import ExportCheck
from api.models.family import FamilyParams
from api.models.finger import Finger
from api.models.job import JobKind, JobStatus
from api.models.job_pose import PoseScore
from api.models.job_spec import SimBackend
from api.models.offset_grid import OffsetGrid
from api.models.outcome import Outcomes
from api.models.part import Part
from api.models.piece import Piece
from api.models.task import Task, TaskKind
from api.models.validation import PhysicalBadge, Validation

BASELINE_LABELS = {"stock": "STOCK", "imprint": "IMP"}
FILE_SUFFIXES = {"step": ".step", "stl_left": "_L.stl", "stl_right": "_R.stl", "print_sheet": "_print_sheet.pdf"}
DIRECTIONS = ("+x", "+x+y", "+y", "-x+y", "-x", "-x-y", "-y", "+x-y")  # every 45 degrees from the closing direction


class CardScore(BaseModel):
    """One design's final-grid score at the job's own target, for a job card."""

    label: str
    success: float
    capture_radius_mm: float | None


class JobCard(BaseModel):
    """One experiment in the job list, and each server-sent event while it runs. For an evaluation job, winner is its
    best finger (label: the finger code) and stock its stock fingers; n_done counts fingers simulated at a grasp, and
    round / n_rounds sim requests."""

    id: str
    experiment_id: str
    name: str
    kind: JobKind = "generation"
    batch_id: str | None = None  # evaluation jobs created together, one per part
    part_id: str
    part_name: str | None  # the uploaded file's name
    task_kind: TaskKind
    sim_backend: SimBackend  # the badge: mock results are never predictions
    status: JobStatus
    round: int  # rounds done ("round x of y")
    n_rounds: int
    n_done: int  # designs evaluated, final test included
    n_total: int
    best_value: float | None  # best expected success so far (search grid), then D1's on the final grid
    winner: CardScore | None = None  # done: D1 at the target ...
    stock: CardScore | None = None  # ... against the stock fingers
    failure: str | None = None  # failed: one line ...
    failed_step: int | None = None  # ... and the input step that fixes it, when known
    physical_badge: PhysicalBadge = "none"
    created: float
    finished: float | None = None
    duplicated_from: str | None = None


class ResultsHeader(BaseModel):
    job_id: str
    name: str
    experiment_id: str
    status: JobStatus
    sim_backend: SimBackend
    cell_profile_name: str | None
    cell_profile_version: int | None
    part_name: str | None
    task: Task  # what the numbers below are scored for: the job's own, or the re-score's
    error: ErrorModel
    rescored: bool  # True when task or error differ from the job's own
    created: float
    finished: float | None


class DesignScore(BaseModel):
    """One final-test design at the target error model and task."""

    label: str
    kind: DesignKind
    search: str  # the search it came from, or "baseline"
    success: float  # expected success
    capture_radius_mm: float | None  # every grasp succeeded out to this offset; None if even the centre failed
    task_metric: float | None  # place and insert: the share of held grasps within tolerance; None for pick and drop
    # A job covering several resting poses: the score in each (success above is weighted over them, the capture radius
    # the smallest). None for one pose.
    poses: list[PoseScore] | None = None


class ResultsSummary(BaseModel):
    best: DesignScore  # D1
    stock: DesignScore | None
    imprint: DesignScore | None
    leader: str  # the design scoring best at these settings: D1 unless a re-score moved another ahead
    gain_vs_stock: float | None  # D1's success minus the stock fingers'
    gain_vs_imprint: float | None
    designs_evaluated: int  # designs the search tried (baselines and the final re-tests not counted)
    task_metric_label: str | None  # what task_metric measures, e.g. "held grasps within 1 mm"


class Curve(BaseModel):
    label: str
    kind: DesignKind
    success: dict[str, float]  # sigma in mm, as text ("0.5", "1", ...) -> expected success, with the target's bias and yaw


class Curves(BaseModel):
    sigmas_mm: list[float]
    target_sigma_mm: float  # marked on the plot ...
    target_range_mm: tuple[float, float] | None  # ... or this band, when designing for a range
    designs: list[Curve]  # every final design


class MapPoint(BaseModel):
    dx: float
    dy: float
    yaw_deg: float
    weight: float  # the point's probability under the target error model
    held: bool
    success: bool  # held, and whatever the task adds (transport, tolerance)


class HeldMap(BaseModel):
    label: str
    points: list[MapPoint]  # the final grid's points
    pose: str | None = None  # the resting pose's key ("p0", ...) when the job covers several; None for one
    pose_label: str | None = None


class InHandView(BaseModel):
    """Where D1 holds the part after the lift, over the grasps that held (for the place and insert histograms)."""

    label: str
    n_held: int
    offsets_mm: list[float]  # per held grasp with a reported pose: 3-D offset from a centred part
    tilts_deg: list[float]
    weights: list[float]  # each one's probability under the target error model
    offset_tolerance_mm: float | None
    tilt_tolerance_deg: float | None
    within_tolerance: float | None  # the task metric


class MissGroup(BaseModel):
    direction: str  # "+x" (along the closing direction), "+x+y", "+y", ...
    angle_deg: float
    missed: int
    points: int
    lost: float  # probability lost to these misses under the target error model
    nearest_miss_mm: float | None


class MissDistance(BaseModel):
    radius_mm: float
    missed: int
    points: int


class FailureView(BaseModel):
    """Where D1 fails: its missed offsets by direction and by distance, and the caveats every result carries."""

    label: str
    centre_missed: bool
    first_miss_mm: float | None  # the smallest offset with a miss; None when nothing on the grid missed
    by_direction: list[MissGroup]
    by_distance: list[MissDistance]
    caveats: list[str]


class BestFinger(BaseModel):
    label: str
    kind: DesignKind
    search: str
    params: FamilyParams | None
    grasp_pose: dict[str, Any]
    grasp_pose_text: str  # the same, to copy into a robot program
    files: list[str]  # "step", "stl_left", "stl_right", "print_sheet": what GET .../designs/D1/... serves
    checks: list[ExportCheck]
    download_blocked: bool  # a blocking check failed: the files are not offered


class FinalRow(BaseModel):
    label: str
    kind: DesignKind
    search: str
    params: FamilyParams | None
    success: float
    capture_radius_mm: float | None
    task_metric: float | None
    print_selected: bool  # in the job's print selection
    poses: list[PoseScore] | None = None  # per resting pose, when the job covers several


class SearchProgress(BaseModel):
    key: str
    family: str
    method: str  # "single", "sobol" or "bo"
    budget: int
    n_initial: int
    batch_size: int
    patience: int
    designs_evaluated: int
    rounds: int
    best: float | None
    best_so_far: list[float]  # after each design, in the order they were evaluated
    stop_reason: str | None  # "budget" or "patience" once the search is over; None while it runs


class RunDetails(BaseModel):
    searches: list[SearchProgress]
    rounds: int
    n_rounds: int
    error: ErrorModel  # the job's own
    task: Task
    seed: int
    grids: dict[str, Any]  # the search and final grids
    versions: dict[str, str | None] = {}  # filled in when the run finishes
    gpu: str | None = None
    sim: dict[str, Any] = {}
    runtime_s: float | None = None
    warnings: list[str] = []  # the cell profile vs the sim server's settings and the twin


class ResultsView(BaseModel):
    """The results page. The sections built from the final test are None (or empty) until it has run."""

    header: ResultsHeader
    summary: ResultsSummary | None
    curves: Curves | None
    held_maps: list[HeldMap]  # D1 and STOCK
    in_hand: InHandView | None
    failures: FailureView | None
    best_finger: BestFinger | None
    final_table: list[FinalRow]
    physical: Validation
    run: RunDetails


class DesignExport(BaseModel):
    """A final design's printable files on disk and the checks they passed."""

    label: str
    files: dict[str, str]  # "step", "stl_left", "stl_right", "print_sheet" -> path
    checks: list[ExportCheck]

    @property
    def blocked(self) -> list[ExportCheck]:
        return [check for check in self.checks if check.blocking and not check.ok]


class FingerPreview(BaseModel):
    """Both fingers of one final design and the part they grip, for the 3D preview: gripper frame, mm, jaws closed.
    Open the jaws by moving the left finger +jaw_open_mm along x and the right one -jaw_open_mm."""

    label: str
    part: Part  # in the resting pose shown
    extent_mm: tuple[float, float, float]  # the part along the closing direction, across it, and its height
    jaw_open_mm: float
    finger: Finger  # the left finger (+x jaw): its pieces, grasp settings and closed gap
    right: list[Piece]  # the right finger: the left one mirrored in x
    pose: str = "p0"  # the resting pose shown (the job's poses' keys); the primary by default
    pose_label: str | None = None


def task_metric(outcomes: Outcomes, task: Task, weights: list[float]) -> float | None:
    """For pick and place or insert: of the grasps that held (and stayed held through the transport move, if the task
    has one and it was simulated), the share whose in-hand pose is within the task's tolerances, weighted by the error
    model. None for pick and drop, or when nothing held."""
    if task.kind == "drop":
        return None
    after = outcomes.held_after_transport if task.transport else None
    held = [h and (after is None or after[i]) for i, h in enumerate(outcomes.held)]
    total = sum(w for w, h in zip(weights, held, strict=True) if h)
    if total <= 0:
        return None
    within = sum(w for w, h, pose in zip(weights, held, outcomes.in_hand, strict=True) if h and task.within_tolerance(pose))
    return within / total


def task_metric_label(task: Task) -> str | None:
    if task.kind == "place":
        return f"held grasps within {task.offset_tolerance_mm:g} mm"
    if task.kind == "insert":
        return f"held grasps within {task.offset_tolerance_mm:g} mm and {task.tilt_tolerance_deg:g} deg of tilt"
    return None


def misses(grid: OffsetGrid, success: list[bool], weights: list[float]) -> tuple[bool, list[MissGroup], list[MissDistance]]:
    """A design's failed grid points grouped by direction (the nearest of eight, 45 degrees apart) and by distance (the
    grid's rings), counted over every yaw layer: (centre missed, by direction, by distance)."""
    groups = {i: {"missed": 0, "points": 0, "lost": 0.0, "nearest": None} for i in range(len(DIRECTIONS))}
    rings = {r: [0, 0] for r in grid.radii_mm}
    centre_missed = False
    for point, ok, w in zip(grid.points(), success, weights, strict=True):
        r = math.hypot(point["dx"], point["dy"])
        if r < 1e-9:
            centre_missed |= not ok
            continue
        sector = round(math.degrees(math.atan2(point["dy"], point["dx"])) / 45) % len(DIRECTIONS)
        group = groups[sector]
        group["points"] += 1
        ring = rings[min(rings, key=lambda radius: abs(radius - r))]
        ring[1] += 1
        if not ok:
            group["missed"] += 1
            group["lost"] += w
            group["nearest"] = r if group["nearest"] is None else min(group["nearest"], r)
            ring[0] += 1
    by_direction = [
        MissGroup(
            direction=DIRECTIONS[i],
            angle_deg=45.0 * i,
            missed=g["missed"],
            points=g["points"],
            lost=g["lost"],
            nearest_miss_mm=None if g["nearest"] is None else round(g["nearest"], 6),
        )
        for i, g in groups.items()
    ]
    by_distance = [MissDistance(radius_mm=r, missed=m, points=n) for r, (m, n) in rings.items()]
    return centre_missed, by_direction, by_distance


SLUG_MAX = 40  # long names would push export paths past Windows' 260-character limit; the EXP id keeps files unique


def slug(name: str) -> str:
    """A name as a file-name prefix: letters, digits, dots, dashes and underscores (anything else becomes a dash), at most
    SLUG_MAX characters."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)[:SLUG_MAX].strip("-.") or "experiment"


def file_stem(name: str, experiment_id: str, label: str, sim_backend: SimBackend) -> str:
    """What every file a design exports is named from (D14): <slug(name)>_<EXP-id>_<label>, plus _MOCK for mock results,
    so a file never loses its badge."""
    return f"{slug(name)}_{experiment_id}_{label}" + ("_MOCK" if sim_backend == "mock" else "")


def grasp_pose_text(pose: dict[str, Any]) -> str:
    """A grasp pose as "key: value" lines, for pasting into a robot program's comments or a work instruction. A job
    covering several resting poses adds a block per pose."""
    lines = []
    for key, value in pose.items():
        if key == "poses" and isinstance(value, list):
            for i, each in enumerate(value, 1):
                lines.append(f"pose {i}:")
                lines += ["  " + line for line in grasp_pose_text(each).splitlines()]
            continue
        if isinstance(value, list | tuple):
            value = ", ".join(f"{v:g}" if isinstance(v, float) else str(v) for v in value)
        elif isinstance(value, float):
            value = f"{value:g}"
        lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def mirrored(pieces: list[Piece]) -> list[Piece]:
    """Pieces mirrored in x (the other finger): x -> -x, with each triangle's winding reversed so its faces still point
    out."""
    return [
        Piece(points=[(-x, y, z) for x, y, z in piece.points], triangles=[(a, c, b) for a, b, c in piece.triangles]) for piece in pieces
    ]
