import pytest
from pydantic import ValidationError

from api.models.grasp import GraspChoice
from api.models.job_spec import JobSpec, PoseGrasp

GRASP = GraspChoice(angle_deg=0)


def spec(**values) -> JobSpec:
    return JobSpec(**{"part_id": "part", "cell_profile_id": 1, **values})


def test_a_spec_gives_its_poses_with_their_grasps_or_one_grasp():
    covered = spec(poses=[PoseGrasp(pose=1, grasp=GRASP), PoseGrasp(pose=0, grasp=GraspChoice(angle_deg=90))])

    assert [p.pose for p in covered.poses] == [1, 0] and covered.grasp is None
    assert spec(grasp=GRASP).poses == []  # as every spec was before jobs covered poses
    # A spec stored then still loads
    assert JobSpec.model_validate_json('{"part_id": "p", "cell_profile_id": 1, "grasp": {"angle_deg": 0}}').grasp == GRASP


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({}, "give the resting poses"),
        ({"grasp": GRASP, "poses": [PoseGrasp(pose=0, grasp=GRASP)]}, "give the resting poses"),
        ({"poses": [PoseGrasp(pose=0, grasp=GRASP), PoseGrasp(pose=0, grasp=GRASP)]}, "each resting pose can be chosen once"),
        ({"poses": [PoseGrasp(pose="as_authored", grasp=GRASP), PoseGrasp(pose=0, grasp=GRASP)]}, "it can only be the one pose"),
        ({"poses": [PoseGrasp(pose=i, grasp=GRASP) for i in range(5)]}, "at most 4"),
    ],
)
def test_a_spec_needs_one_grasp_per_distinct_pose(values, message):
    with pytest.raises(ValidationError, match=message):
        spec(**values)
