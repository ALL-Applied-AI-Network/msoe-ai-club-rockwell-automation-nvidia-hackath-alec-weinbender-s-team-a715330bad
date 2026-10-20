"""The service entry for a grasp batch: the job routers/evaluations.py queues for the main thread. Isaac-free.

evaluate_batch does the bookkeeping: each design's grasp settings and warnings, the stock-fit skip, planning every
design before anything is simulated (so an IK failure fails fast), packing designs x offsets into chunks of one grasp per
environment, turning each offset into the part's true pose, turning what the cell measured into outcomes (held, the
in-hand pose, held after transport), and the timing log. Each chunk goes to the cell (clients/isaac.py, the only Isaac
code), which edits the stage when needed and runs the physics. Tests drive it with a fake cell that satisfies the Cell
protocol below.
"""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import EnvGrasp, GraspSettings, Transport
from sim_server.models.gripper import GripperGeometry
from sim_server.models.outcome import BatchOutcome, GraspOutcome
from sim_server.models.part import Part
from sim_server.models.pose import InHandPose
from sim_server.models.recording import RecordView
from sim_server.robot.poses import in_hand_pose, nominal_pose, true_pose
from sim_server.services.batches import chunk_grasps, design_warnings, grasp_settings, stock_fits

if TYPE_CHECKING:  # motion.py needs numpy; keep it out of the router's import chain
    from sim_server.robot.motion import GraspPlan

logger = logging.getLogger(__name__)


class Planner(Protocol):
    site_xy: tuple[float, float]
    spread_xy: tuple[float, float]  # world direction toward JawL at the grasp

    def plan(self, tip_height: float, jaw_close: float, transport: Transport | None = None) -> "GraspPlan": ...

    def lift_tip(self, tip_height: float) -> tuple[float, float, float]:
        """The commanded fingertip point (G's origin) at the end of the lift, base frame."""
        ...


class Cell(Protocol):
    """What evaluate_batch needs from the simulator: clients/isaac.GraspCell, or a fake in tests."""

    geometry: GripperGeometry
    planner: Planner
    env_count: int

    def run_chunk(self, part: Part, grasps: list[EnvGrasp], grip_force: float | None) -> list[GraspOutcome]:
        """grasps[e] runs on environment e; environments past len(grasps) sit idle. grip_force is the per-jaw force
        limit (newtons; None: the twin's drive). The batch's transport is in the grasps' plans. Returns one outcome per
        grasp, with the part's pose at the end of the lift in the base frame."""
        ...

    def record(
        self, part: Part, grasp: EnvGrasp, grip_force: float | None, views: list[RecordView], size: tuple[int, int], out_dir: Path
    ) -> tuple[GraspOutcome, int, dict[RecordView, str]]:
        """One grasp, as run_chunk runs it, with the cameras on: (its outcome, the frame count, view -> mp4 path)."""
        ...


def evaluate_batch(cell: Cell, batch: GraspBatch) -> BatchOutcome:
    """Main thread only (it drives Isaac through the cell). One row per design, one entry per offset."""
    started = time.perf_counter()
    geo, planner = cell.geometry, cell.planner
    n_offsets = len(batch.offsets)
    held = [[False] * n_offsets for _ in batch.designs]
    in_hand: list[list[InHandPose | None]] = [[None] * n_offsets for _ in batch.designs]
    after = None if batch.transport is None else [[False] * n_offsets for _ in batch.designs]
    settings = [grasp_settings(design, batch.part, geo) for design in batch.designs]
    pairs = []
    for d, (design, setting) in enumerate(zip(batch.designs, settings, strict=True)):
        for warning in design_warnings(design, setting):
            logger.warning("Design %s: %s", design.id, warning)
        if design.is_stock and not stock_fits(batch.part, geo):
            logger.warning(
                "Design %s: the part is %.1f mm wide but the open stock tips are %.1f mm apart; "
                "every grasp counts as dropped, none simulated",
                design.id,
                batch.part.width * 1000,
                geo.open_tip_gap * 1000,
            )
            continue
        planner.plan(setting.tip_height, setting.jaw_close, batch.transport)  # raises GraspPlanError before anything runs
        pairs += [(d, o) for o in range(n_offsets)]

    nominal = nominal_pose(batch.part, planner.spread_xy, geo.surface_dz, planner.site_xy)
    chunks = chunk_grasps(pairs, cell.env_count)
    for n, chunk in enumerate(chunks):
        chunk_started = time.perf_counter()
        grasps = [
            EnvGrasp(
                design=batch.designs[d],
                plan=planner.plan(settings[d].tip_height, settings[d].jaw_close, batch.transport),
                pose=true_pose(nominal, planner.spread_xy, batch.offsets[o]),
            )
            for d, o in chunk
        ]
        first = grasps[0].pose
        logger.debug("Env 0: part centre (base frame) %s, yaw %.2f deg; JawL toward %s", first.position, first.yaw_deg, planner.spread_xy)
        outcomes = cell.run_chunk(batch.part, grasps, batch.grip_force)
        for (d, o), outcome in zip(chunk, outcomes, strict=True):
            held[d][o] = bool(outcome.held)
            in_hand[d][o] = in_hand_of(outcome, settings[d], batch.part, planner)
            if after is not None:
                after[d][o] = bool(outcome.held_after_transport)
        logger.debug("Chunk %d/%d: %d grasps in %.2f s", n + 1, len(chunks), len(chunk), time.perf_counter() - chunk_started)

    elapsed = time.perf_counter() - started
    logger.info(
        "Batch done: %d design(s) x %d offset(s), %d grasps simulated in %d chunk(s), %.1f s (%.2f grasps/s); "
        "grip force %s N, transport %s; held per design: %s; after transport: %s",
        len(batch.designs),
        n_offsets,
        len(pairs),
        len(chunks),
        elapsed,
        len(pairs) / elapsed if elapsed else 0.0,
        "(twin's)" if batch.grip_force is None else batch.grip_force,
        batch.transport,
        {design.id: sum(row) for design, row in zip(batch.designs, held, strict=True)},
        None if after is None else {design.id: sum(row) for design, row in zip(batch.designs, after, strict=True)},
    )
    return BatchOutcome(
        held=tuple(map(tuple, held)),
        in_hand=tuple(map(tuple, in_hand)),
        held_after_transport=None if after is None else tuple(map(tuple, after)),
    )


def in_hand_of(outcome: GraspOutcome, settings: GraspSettings, part: Part, planner: Planner) -> InHandPose | None:
    """Where a held part sits in the commanded gripper frame at the end of the lift, relative to a centred part
    (half its height above the fingertips' plane, which is tip_height above the part's base)."""
    if not outcome.held or outcome.lift_pose is None:
        return None
    pose = outcome.lift_pose
    return in_hand_pose(
        pose.position,
        pose.orientation,
        planner.lift_tip(settings.tip_height),
        planner.spread_xy,
        expected_z=part.height / 2 - settings.tip_height,
        cylinder_axis=part.cylinder_axis,
    )
