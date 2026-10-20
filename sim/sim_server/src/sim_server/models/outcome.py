from pydantic import BaseModel, ConfigDict

from sim_server.models.pose import BodyPose, InHandPose


class GraspOutcome(BaseModel):
    """What the cell measured for one grasp (clients/isaac.GraspCell.run_chunk).

    - held: the part's centre rose more than 25 mm between the end of the approach and the end of the lift.
    - lift_pose: the part's pose at the end of the lift, in its environment's base frame; None when physics blew up.
    - held_after_transport: still more than 25 mm up at the end of the settle; None when the grasp had no transport."""

    model_config = ConfigDict(frozen=True)

    held: bool
    lift_pose: BodyPose | None = None
    held_after_transport: bool | None = None


class BatchOutcome(BaseModel):
    """A batch's answer, one row per design and one entry per offset. in_hand is None where the part wasn't held or the
    grasp wasn't simulated; held_after_transport is None when the batch had no transport move."""

    model_config = ConfigDict(frozen=True)

    held: tuple[tuple[bool, ...], ...]
    in_hand: tuple[tuple[InHandPose | None, ...], ...]
    held_after_transport: tuple[tuple[bool, ...], ...] | None = None
