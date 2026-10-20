import pytest
from pydantic import ValidationError

from sim_server.models.batch import GraspBatch
from sim_server.models.outcome import BatchOutcome, GraspOutcome
from sim_server.models.part import Part
from sim_server.models.pose import BodyPose, InHandPose

CUBE = Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)


def test_a_grasp_outcome_defaults_to_no_pose_and_no_transport():
    outcome = GraspOutcome(held=False)
    assert outcome.lift_pose is None and outcome.held_after_transport is None
    held = GraspOutcome(held=True, lift_pose=BodyPose(position=(0.3, 0.0, 0.13), orientation=(1, 0, 0, 0)), held_after_transport=True)
    assert held.lift_pose.orientation == (1.0, 0.0, 0.0, 0.0)


def test_batch_outcomes_are_frozen():
    outcome = BatchOutcome(held=((True,),), in_hand=((InHandPose(dx=0, dy=0, dz=0, tilt_deg=0, yaw_deg=0),),))
    assert outcome.held_after_transport is None
    with pytest.raises(ValidationError):
        outcome.held = ((False,),)


def test_batches_default_to_the_twins_drive_and_no_transport():
    batch = GraspBatch(part=CUBE, designs=(), offsets=())
    assert batch.grip_force is None and batch.transport is None
    assert GraspBatch(part=CUBE, designs=(), offsets=(), grip_force=20.0, transport="fast").transport == "fast"
    with pytest.raises(ValidationError):
        GraspBatch(part=CUBE, designs=(), offsets=(), transport="warp")
