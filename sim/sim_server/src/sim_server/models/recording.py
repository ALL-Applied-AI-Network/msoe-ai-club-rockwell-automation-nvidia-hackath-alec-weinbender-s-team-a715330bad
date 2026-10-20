"""A grasp recorded on video: what POST /record_grasp films and returns (routers/evaluations.py)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from sim_server.models.pose import InHandPose

# closeup: the fingers and the part at the grasp site, seen across the jaws' closing direction so both fingers show.
# side: the twin's own side camera on the cell, with the arm.
RecordView = Literal["closeup", "side"]
RECORD_VIEWS: tuple[RecordView, ...] = ("closeup", "side")
RECORD_FPS = 30  # one frame per control frame, as robot/motion.FPS: two 1/60 s physics steps


class GraspRecording(BaseModel):
    """One grasp, filmed: its outcome (as evaluate_batch would report it) and one mp4 per view, by path."""

    model_config = ConfigDict(frozen=True)

    held: bool
    in_hand: InHandPose | None
    held_after_transport: bool | None
    frames: int
    files: dict[RecordView, str]
