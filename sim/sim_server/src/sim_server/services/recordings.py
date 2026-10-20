"""The service entry for filming one grasp: the job routers/evaluations.py queues for the main thread. Isaac-free.

It plans the grasp exactly as evaluate_batch does (the design's grasp settings, the motion at the nominal pose, the part's
true pose from the offset), so a recording is the same grasp a batch simulates, then hands it to the cell, which runs it
with the cameras on and writes the videos.
"""

import logging
import time
from pathlib import Path

from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import EnvGrasp, GraspPlanError
from sim_server.models.recording import GraspRecording, RecordView
from sim_server.robot.poses import nominal_pose, true_pose
from sim_server.services.batches import grasp_settings, stock_fits
from sim_server.services.evaluations import Cell, in_hand_of

logger = logging.getLogger(__name__)


def record_grasp(cell: Cell, batch: GraspBatch, views: list[RecordView], size: tuple[int, int], out_dir: Path) -> GraspRecording:
    """Main thread only. batch has one design and one offset; the videos go to out_dir/<view>.mp4."""
    if len(batch.designs) != 1 or len(batch.offsets) != 1:
        raise ValueError("a recording is one design at one offset")
    started = time.perf_counter()
    design, geo, planner = batch.designs[0], cell.geometry, cell.planner
    settings = grasp_settings(design, batch.part, geo)
    if design.is_stock and not stock_fits(batch.part, geo):
        raise GraspPlanError(
            f"the part is {batch.part.width * 1000:.1f} mm wide but the open stock tips are {geo.open_tip_gap * 1000:.1f} mm "
            "apart: there's no grasp to film"
        )
    plan = planner.plan(settings.tip_height, settings.jaw_close, batch.transport)
    nominal = nominal_pose(batch.part, planner.spread_xy, geo.surface_dz, planner.site_xy)
    grasp = EnvGrasp(design=design, plan=plan, pose=true_pose(nominal, planner.spread_xy, batch.offsets[0]))
    outcome, frames, files = cell.record(batch.part, grasp, batch.grip_force, views, size, out_dir)
    logger.info(
        "Recorded design %s: %s, %d frames of %s at %dx%d in %.1f s",
        design.id,
        "held" if outcome.held else "missed",
        frames,
        ", ".join(views),
        *size,
        time.perf_counter() - started,
    )
    return GraspRecording(
        held=outcome.held,
        in_hand=in_hand_of(outcome, settings, batch.part, planner),
        held_after_transport=outcome.held_after_transport,
        frames=frames,
        files=files,
    )
