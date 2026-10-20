import pytest

from api.models.offset_grid import OffsetGrid
from api.models.outcome import Outcomes
from api.models.piece import Piece
from api.models.results import file_stem, grasp_pose_text, mirrored, misses, slug, task_metric
from api.models.task import Task


def test_file_names_start_with_the_slug_and_experiment_id_and_keep_the_mock_badge():
    assert slug("vial cap / groove (copy)") == "vial-cap-groove-copy" and slug("  ") == "experiment"
    assert file_stem("vial-cap_2026-10-19", "EXP-0042", "D1", "mock") == "vial-cap_2026-10-19_EXP-0042_D1_MOCK"
    assert file_stem("cap", "EXP-0042", "IMP", "isaac") == "cap_EXP-0042_IMP"


def test_the_task_metric_is_the_weighted_share_of_held_grasps_within_tolerance():
    outcomes = Outcomes(held=[True, True, True, False], in_hand=[(0, 0, 0, 0, 0), (0, 2, 0, 0, 0), (0, 0.5, 0, 5, 0), None])
    weights = [0.4, 0.2, 0.2, 0.2]

    assert task_metric(outcomes, Task(), weights) is None
    assert task_metric(outcomes, Task(kind="place", offset_tolerance_mm=1.0), weights) == pytest.approx(0.6 / 0.8)
    assert task_metric(outcomes, Task(kind="insert", offset_tolerance_mm=1.0, tilt_tolerance_deg=2.0), weights) == pytest.approx(0.4 / 0.8)
    assert task_metric(Outcomes.dropped(4), Task(kind="place", offset_tolerance_mm=1.0), weights) is None


def test_misses_are_grouped_by_direction_and_ring():
    grid = OffsetGrid(radii_mm=[1, 2], n_directions=4)  # the centre, then +x, +y, -x, -y on each ring
    success = [True, True, True, True, True, False, True, True, True]  # misses only at 2 mm toward +x

    centre_missed, by_direction, by_distance = misses(grid, success, [1 / 9] * 9)

    assert not centre_missed
    plus_x = by_direction[0]
    assert (plus_x.direction, plus_x.missed, plus_x.points, plus_x.nearest_miss_mm) == ("+x", 1, 2, 2.0)
    assert plus_x.lost == pytest.approx(1 / 9) and sum(g.missed for g in by_direction) == 1
    assert [(d.radius_mm, d.missed, d.points) for d in by_distance] == [(1, 0, 4), (2, 1, 4)]


def test_mirrored_pieces_keep_their_faces_pointing_out():
    piece = Piece(points=[(1, 0, 0), (2, 0, 0), (1, 1, 0), (1, 0, 1)], triangles=[(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)])

    (mirror,) = mirrored([piece])

    assert mirror.points == [(-1, 0, 0), (-2, 0, 0), (-1, 1, 0), (-1, 0, 1)]
    assert mirror.triangles == [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)]


def test_a_grasp_pose_reads_as_key_value_lines():
    text = grasp_pose_text({"tip_height_mm": 3.5, "grasp_centre_mm": [0.0, -0.25], "approach": "top-down"})

    assert text == "tip_height_mm: 3.5\ngrasp_centre_mm: 0, -0.25\napproach: top-down\n"
