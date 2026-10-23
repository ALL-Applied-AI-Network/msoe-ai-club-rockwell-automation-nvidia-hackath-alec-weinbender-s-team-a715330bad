"""The resting poses a job covers, and how a design's results in each become one score.

A part can come to rest on the table more than one way. A job covers one or more of its resting poses (input step 2),
each with its own grasp (step 5), and every design is simulated in every pose: one physical finger, built for the
primary pose (the likeliest), gripping each of the others as api/models/finger.py: regrip() works out. A design's score
is the mean of its expected success in each pose weighted by w_k = p_k / (sum of the covered poses' p): how often the
part comes to rest that way, among the poses the job covers. That assumes the cell recognises each part's pose and runs
its grasp. Its capture radius is the smallest over the poses: it holds out to r in every pose.

With one pose the weight is exactly 1, so a one-pose job scores exactly as a job did before jobs covered poses.
"""

from typing import Literal

from pydantic import BaseModel

from api.models.error_model import ErrorModel
from api.models.grasp import GraspChoice
from api.models.offset_grid import OffsetGrid
from api.models.part import Part
from api.models.resting_pose import RestingPose

PoseChoice = int | Literal["as_authored"]  # an index into GET /api/parts/{id}/poses, or the CAD file's own orientation
PRIMARY = "p0"


class JobPose(BaseModel):
    """One resting pose a job covers, as the job snapshots it: its likelihood and weight, its grasp, and the part as the
    gripper meets it in that pose."""

    key: str  # "p0" is the primary (the likeliest), then "p1", ... by likelihood
    label: str | None = None  # "lying on its side"; None for a job from before jobs covered poses
    choice: PoseChoice | None = None  # what step 2 chose; None for a job from before
    probability: float | None = None  # trimesh's likelihood; None for "as in the CAD file"
    weight: float = 1.0  # its share of the score
    resting: RestingPose | None = None
    grasp: GraspChoice
    part: Part  # in this pose, turned to its grasp


class PoseScore(BaseModel):
    """One design's score in one pose, at the view's error model and task."""

    key: str
    label: str | None
    weight: float
    success: float
    capture_radius_mm: float | None


def pose_weights(probabilities: list[float | None]) -> list[float]:
    """Each pose's weight: its likelihood over the covered poses' total, or equal shares where a likelihood isn't
    known ("as in the CAD file")."""
    total = sum(p for p in probabilities if p is not None)
    if any(p is None for p in probabilities) or total <= 0:
        return [1 / len(probabilities)] * len(probabilities)
    return [p / total for p in probabilities]


def score_poses(
    successes: list[list[bool]], poses: list[JobPose], grid: OffsetGrid, error: ErrorModel
) -> tuple[float, float | None, list[PoseScore]]:
    """A design's (success, capture radius, per-pose scores) from its per-point successes in each pose, in the job's
    pose order: the weighted expected success, and the smallest capture radius (None if any pose missed even the
    centre)."""
    scores = [
        PoseScore(
            key=pose.key,
            label=pose.label,
            weight=pose.weight,
            success=grid.expected_success(success, error),
            capture_radius_mm=grid.capture_radius(success),
        )
        for pose, success in zip(poses, successes, strict=True)
    ]
    rate = sum(score.weight * score.success for score in scores)
    radii = [score.capture_radius_mm for score in scores]
    return rate, None if None in radii else min(radii), scores
