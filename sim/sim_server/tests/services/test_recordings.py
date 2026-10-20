"""services/recordings.py: a recording is the batch's own grasp (settings, plan, true pose), handed to the cell to film."""

import pytest

from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import GraspPlanError
from sim_server.models.outcome import GraspOutcome
from sim_server.models.pose import BodyPose
from sim_server.robot.poses import NOMINAL_SITE_XY, yaw_quaternion
from sim_server.services.batches import design_from_mm, offset_from_mm, part_from_mm
from sim_server.services.recordings import record_grasp

SPREAD, LIFT = (0.0, 1.0), 0.13


class FakePlanner:
    site_xy, spread_xy = NOMINAL_SITE_XY, SPREAD

    def __init__(self, surface_dz):
        self.surface_dz, self.plans = surface_dz, []

    def plan(self, tip_height, jaw_close, transport=None):
        self.plans.append((round(tip_height, 7), round(jaw_close, 7), transport))
        return self.plans[-1]

    def lift_tip(self, tip_height):
        return (*self.site_xy, self.surface_dz + tip_height + LIFT)


class FilmingCell:
    """Lifts the part straight up and "writes" one small file per view."""

    def __init__(self, geometry):
        self.geometry, self.env_count, self.planner = geometry, 1, FakePlanner(geometry.surface_dz)
        self.recorded = []

    def record(self, part, grasp, grip_force, views, size, out_dir):
        self.recorded.append((part, grasp, grip_force, views, size))
        files = {}
        for view in views:
            path = out_dir / f"{view}.mp4"
            path.write_bytes(f"{view} video".encode())
            files[view] = str(path)
        x, y, z = grasp.pose.position
        lifted = BodyPose(position=(x, y, z + LIFT), orientation=yaw_quaternion(grasp.pose.yaw_deg))
        return GraspOutcome(held=True, lift_pose=lifted), 147, files


def one_grasp(design, dx_mm=1.0, **settings) -> GraspBatch:
    return GraspBatch(
        part=part_from_mm("box", box_mm=[10, 10, 10], mass_g=4),
        designs=(design,),
        offsets=(offset_from_mm(dx_mm, 0, 0),),
        **settings,
    )


def test_a_recording_films_the_batchs_own_grasp(geo, tmp_path):
    cell = FilmingCell(geo)

    recording = record_grasp(cell, one_grasp(design_from_mm("stock"), transport="slow"), ["closeup", "side"], (640, 360), tmp_path)

    [(_, grasp, grip_force, views, size)] = cell.recorded
    assert grasp.pose.position[1] - NOMINAL_SITE_XY[1] == pytest.approx(0.001)  # the offset moved the part, not the robot
    assert grasp.plan[2] == "slow" and grip_force is None and views == ["closeup", "side"] and size == (640, 360)
    assert recording.held and recording.frames == 147 and recording.held_after_transport is None
    assert recording.in_hand is not None and recording.in_hand.dy == pytest.approx(0.0, abs=1e-9)  # lifted as placed
    assert {view: open(path).read() for view, path in recording.files.items()} == {"closeup": "closeup video", "side": "side video"}


def test_stock_fingers_that_cant_open_around_the_part_have_nothing_to_film(geo, tmp_path):
    wide = one_grasp(design_from_mm("stock")).model_copy(update={"part": part_from_mm("box", box_mm=[40, 10, 10], mass_g=4)})

    with pytest.raises(GraspPlanError, match="no grasp to film"):
        record_grasp(FilmingCell(geo), wide, ["closeup"], (640, 360), tmp_path)


def test_a_recording_is_one_design_at_one_offset(geo, tmp_path):
    two = one_grasp(design_from_mm("stock")).model_copy(update={"offsets": (offset_from_mm(0, 0, 0), offset_from_mm(1, 0, 0))})

    with pytest.raises(ValueError, match="one design at one offset"):
        record_grasp(FilmingCell(geo), two, ["closeup"], (640, 360), tmp_path)
