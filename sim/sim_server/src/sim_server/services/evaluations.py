"""The service entry for a grasp batch: the job routers/evaluations.py queues for the main thread. Isaac-free.

evaluate_batch does the bookkeeping: each design's grasp settings and warnings, the stock-fit skip, planning every
design before anything is simulated (so an IK failure fails fast), packing designs x offsets into chunks of one grasp per
environment, turning each offset into the part's true pose, assembling the rows, and the timing log. Each chunk goes to
the cell (clients/isaac.py, the only Isaac code), which edits the stage when needed and runs the physics. Tests drive it
with a fake cell that satisfies the Cell protocol below.
"""

import logging
import time
from typing import TYPE_CHECKING, Protocol

from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import EnvGrasp
from sim_server.models.gripper import GripperGeometry
from sim_server.models.part import Part
from sim_server.robot.poses import nominal_pose, true_pose
from sim_server.services.batches import chunk_grasps, design_warnings, grasp_settings, stock_fits

if TYPE_CHECKING:  # motion.py needs numpy; keep it out of the router's import chain
    from sim_server.robot.motion import GraspPlan

logger = logging.getLogger(__name__)


class Planner(Protocol):
    site_xy: tuple[float, float]
    spread_xy: tuple[float, float]  # world direction toward JawL at the grasp

    def plan(self, tip_height: float, jaw_close: float) -> "GraspPlan": ...


class Cell(Protocol):
    """What evaluate_batch needs from the simulator: clients/isaac.GraspCell, or a fake in tests."""

    geometry: GripperGeometry
    planner: Planner
    env_count: int

    def run_chunk(self, part: Part, grasps: list[EnvGrasp]) -> list[bool]:
        """grasps[e] runs on environment e; environments past len(grasps) sit idle. Returns held per grasp."""
        ...


def evaluate_batch(cell: Cell, batch: GraspBatch) -> list[list[bool]]:
    """Main thread only (it drives Isaac through the cell). One row per design, one bool per offset: whether the part
    was held."""
    started = time.perf_counter()
    geo, planner = cell.geometry, cell.planner
    held = [[False] * len(batch.offsets) for _ in batch.designs]
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
        planner.plan(setting.tip_height, setting.jaw_close)  # raises GraspPlanError before anything is simulated
        pairs += [(d, o) for o in range(len(batch.offsets))]

    nominal = nominal_pose(batch.part, planner.spread_xy, geo.surface_dz, planner.site_xy)
    chunks = chunk_grasps(pairs, cell.env_count)
    for n, chunk in enumerate(chunks):
        chunk_started = time.perf_counter()
        grasps = [
            EnvGrasp(
                design=batch.designs[d],
                plan=planner.plan(settings[d].tip_height, settings[d].jaw_close),
                pose=true_pose(nominal, planner.spread_xy, batch.offsets[o]),
            )
            for d, o in chunk
        ]
        first = grasps[0].pose
        logger.debug("Env 0: part centre (base frame) %s, yaw %.2f deg; JawL toward %s", first.position, first.yaw_deg, planner.spread_xy)
        results = cell.run_chunk(batch.part, grasps)
        for (d, o), ok in zip(chunk, results, strict=True):
            held[d][o] = bool(ok)
        logger.debug("Chunk %d/%d: %d grasps in %.2f s", n + 1, len(chunks), len(chunk), time.perf_counter() - chunk_started)

    elapsed = time.perf_counter() - started
    logger.info(
        "Batch done: %d design(s) x %d offset(s), %d grasps simulated in %d chunk(s), %.1f s (%.2f grasps/s); held per design: %s",
        len(batch.designs),
        len(batch.offsets),
        len(pairs),
        len(chunks),
        elapsed,
        len(pairs) / elapsed if elapsed else 0.0,
        {design.id: sum(row) for design, row in zip(batch.designs, held, strict=True)},
    )
    return held
