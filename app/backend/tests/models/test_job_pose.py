import math

import pytest

from api.models.error_model import ErrorModel
from api.models.grasp import GraspChoice
from api.models.job_pose import JobPose, pose_weights, score_poses
from api.models.offset_grid import OffsetGrid
from api.models.part import Part

GRID, ERROR = OffsetGrid(), ErrorModel()


def pose(key: str, weight: float) -> JobPose:
    return JobPose(key=key, weight=weight, grasp=GraspChoice(angle_deg=0), part=Part())


def held_within(radius_mm: float) -> list[bool]:
    return [math.hypot(p["dx"], p["dy"]) <= radius_mm + 1e-9 for p in GRID.points()]


def test_weights_are_the_likelihoods_over_the_covered_poses():
    assert pose_weights([0.6, 0.3]) == pytest.approx([2 / 3, 1 / 3])
    assert pose_weights([0.13]) == [1.0]
    assert pose_weights([None]) == [1.0]  # "as in the CAD file": no likelihood, the one pose


def test_one_pose_scores_exactly_as_its_grid_does():
    success = held_within(5)

    rate, radius, (score,) = score_poses([success], [pose("p0", 1.0)], GRID, ERROR)

    assert rate == GRID.expected_success(success, ERROR) and radius == GRID.capture_radius(success) == 5
    assert (score.key, score.weight, score.success) == ("p0", 1.0, rate)


def test_several_poses_weigh_success_and_hold_out_to_the_smallest_radius():
    wide, narrow = held_within(8), held_within(2)
    poses = [pose("p0", 0.75), pose("p1", 0.25)]

    rate, radius, scores = score_poses([wide, narrow], poses, GRID, ERROR)

    assert rate == pytest.approx(0.75 * GRID.expected_success(wide, ERROR) + 0.25 * GRID.expected_success(narrow, ERROR))
    assert radius == 2 and [s.capture_radius_mm for s in scores] == [8, 2]
    assert score_poses([wide, [False] * GRID.size], poses, GRID, ERROR)[1] is None  # one pose missed even the centre
