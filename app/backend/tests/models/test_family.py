import pytest

from api.models.design import Design
from api.models.family import FAMILIES, GRIP_HEIGHT_FIELD, FamilyChoice, ParamRange, VPadParams


def test_the_v_pad_is_built_and_its_fields_are_in_search_order():
    assert [name for name, family in FAMILIES.items() if family.status == "built"] == ["vpad"]
    assert FAMILIES["vpad"].fields == ["pad_width_mm", "groove_angle_deg", "groove_depth_mm", "slack_mm", "tip_height_mm", "lead_in_mm"]
    assert FAMILIES["cradle"].fields == []


def test_a_flat_v_pad_needs_only_width_slack_and_height():
    params = VPadParams(pad_width_mm=10, slack_mm=2, tip_height_mm=3)

    assert (params.groove_angle_deg, params.groove_depth_mm, params.lead_in_mm) == (180, 0, 0)
    assert Design(params=params).family == "vpad"
    assert Design(kind="stock").family is None


@pytest.mark.parametrize(
    "bad",
    [
        {"locks": {"finger_colour": 1}},
        {"ranges": {"slack_mm": ParamRange(lo=1, hi=2)}, "locks": {"slack_mm": 1.5}},
        {"family": "cradle"},
    ],
    ids=["unknown field", "range and lock", "planned family"],
)
def test_a_choice_is_checked_against_the_familys_fields(bad):
    with pytest.raises(ValueError):
        FamilyChoice(**bad)


def test_a_range_cant_run_backwards():
    with pytest.raises(ValueError, match="backwards"):
        ParamRange(lo=3, hi=1)


def test_the_grasps_grip_height_locks_the_tip_height_over_any_range():
    choice = FamilyChoice(ranges={"tip_height_mm": ParamRange(lo=1, hi=2), "slack_mm": ParamRange(lo=1, hi=2)}, locks={"lead_in_mm": 0})

    locked = choice.with_grip_height(6.5)

    assert GRIP_HEIGHT_FIELD == "tip_height_mm"
    assert locked.locks == {"lead_in_mm": 0, "tip_height_mm": 6.5}
    assert list(locked.ranges) == ["slack_mm"]
    assert choice.with_grip_height(None) is choice
