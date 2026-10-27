import pytest

from api.models.outcome import Outcomes, landing_caveat
from api.models.task import Task, offset_mm

# Four grasps: held and centred; held but 3 mm off and tilted 4 degrees; held with no reported pose; dropped.
OUTCOMES = Outcomes(
    held=[True, True, True, False],
    in_hand=[(0.0, 0.0, 0.0, 0.0, 0.0), (0.0, 3.0, 0.0, 4.0, 0.0), None, None],
    held_after_transport=[True, False, True, False],
)


def test_pick_and_drop_succeeds_wherever_the_part_is_held():
    assert Task().success(OUTCOMES) == [True, True, True, False]


def test_a_transport_move_also_needs_the_part_still_held_after_it():
    assert Task(transport="fast").success(OUTCOMES) == [True, False, True, False]
    no_transport_results = OUTCOMES.model_copy(update={"held_after_transport": None})
    assert Task(transport="fast").success(no_transport_results) == [True, True, True, False], "not reported: the lift decides"


def test_pick_and_place_needs_the_part_within_the_placement_tolerance():
    assert Task(kind="place", offset_tolerance_mm=2).success(OUTCOMES) == [True, False, False, False]
    assert Task(kind="place", offset_tolerance_mm=3).success(OUTCOMES) == [True, True, False, False], "a held part with no pose fails"


def test_pick_and_insert_needs_the_tilt_within_its_tolerance_too():
    assert Task(kind="insert", offset_tolerance_mm=5, tilt_tolerance_deg=5).success(OUTCOMES) == [True, True, False, False]
    assert Task(kind="insert", offset_tolerance_mm=5, tilt_tolerance_deg=3).success(OUTCOMES) == [True, False, False, False]


def test_within_tolerance_is_none_for_a_task_without_one():
    assert Task().within_tolerance((9.0, 9.0, 9.0, 90.0, 0.0)) is None
    assert Task(kind="place", offset_tolerance_mm=1).within_tolerance(None) is False


def test_the_in_hand_offset_is_the_3d_distance():
    assert offset_mm((3.0, 0.0, 4.0, 10.0, 20.0)) == 5


@pytest.mark.parametrize(
    "bad", [{"kind": "place"}, {"kind": "insert", "offset_tolerance_mm": 1}, {"kind": "drop", "offset_tolerance_mm": 0}]
)
def test_a_task_needs_its_tolerances(bad):
    with pytest.raises(ValueError):
        Task(**bad)


def test_a_finger_that_landed_on_the_part_fails_every_task_even_when_the_sim_held_it():
    """Moved past 1 mm or 3 degrees before the jaws closed: a miss. Unmeasured grasps (None) score as before."""
    landed = OUTCOMES.model_copy(update={"landing": [(0.2, 0.5), (1.5, 0.0), (0.0, 4.0), None]})
    assert landed.landed() == [False, True, True, False]
    assert Task().success(landed) == [True, False, False, False]
    assert Task(kind="place", offset_tolerance_mm=3).success(landed) == [True, False, False, False]


def test_outcomes_without_landings_never_count_as_landed():
    assert OUTCOMES.landing is None
    assert OUTCOMES.landed() == [False] * 4


def test_landing_needs_one_entry_per_offset():
    with pytest.raises(ValueError, match="landing"):
        Outcomes(held=[True, False], in_hand=[None, None], landing=[(0.0, 0.0)])


def test_the_landing_caveat_counts_held_grasps_scored_as_misses_or_says_it_wasnt_checked():
    landed = OUTCOMES.model_copy(update={"landing": [(0.2, 0.5), (1.5, 0.0), (0.0, 4.0), None]})
    assert landing_caveat([landed, landed]).startswith("4 of 6 grasps the sim held count as misses")
    assert "isn't checked" in landing_caveat([OUTCOMES])
    nothing_held = Outcomes(held=[False], in_hand=[None])
    assert landing_caveat([nothing_held]) is None
