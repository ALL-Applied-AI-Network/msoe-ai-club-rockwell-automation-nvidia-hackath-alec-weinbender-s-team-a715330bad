import random

import pytest

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.family import FamilyChoice, ParamRange, VPadParams
from api.models.finger import WALL_MM, build_finger, problems
from api.models.part import Part
from api.models.piece import hull_piece
from api.models.search_space import SearchSpace

L_BRACKET = Part(
    shape="mesh",
    pieces=[
        hull_piece([(x, y, z) for x in (-15, -9) for y in (-6, 6) for z in (0, 20)]),
        hull_piece([(x, y, z) for x in (-9, 15) for y in (-6, 6) for z in (0, 6)]),
    ],
)
PARTS = {
    "cap": Part(),
    "cube": Part(shape="box"),
    "lying tube": Part(diameter_mm=17, length_mm=140, axis="y"),
    "tube along the jaws": Part(diameter_mm=17, length_mm=30, axis="x"),
    "standing tube": Part(diameter_mm=17, length_mm=140),
    "L-bracket": L_BRACKET,
}
VPAD_FIELDS = [name for name in VPadParams.model_fields if name != "family"]


def corners_and_samples(n: int, seed: int = 0, samples: int = 24) -> list[list[float]]:
    rng = random.Random(seed)
    return [[0.0] * n, [1.0] * n, *([rng.random() for _ in range(n)] for _ in range(samples))]


def test_grooves_are_searched_only_for_parts_round_from_above():
    assert SearchSpace(PARTS["cap"]).names == VPAD_FIELDS
    for name in ("cube", "lying tube", "tube along the jaws", "L-bracket"):
        assert SearchSpace(PARTS[name]).names == ["pad_width_mm", "slack_mm", "tip_height_mm", "lead_in_mm"], name


def test_inapplicable_fields_stay_at_their_defaults():
    design = SearchSpace(PARTS["cube"]).from_unit([0.3, 0.6, 0.2, 0.9])

    assert (design.params.groove_angle_deg, design.params.groove_depth_mm) == (180.0, 0.0)
    assert design.kind == "search"


@pytest.mark.parametrize("part", PARTS.values(), ids=PARTS.keys())
def test_every_point_of_the_unit_cube_is_a_finger_that_fits(part):
    space = SearchSpace(part)

    for unit in corners_and_samples(len(space.names)):
        design = space.from_unit(unit)
        assert problems(part, build_finger(part, design)) == [], design.params
        again = space.from_unit(space.to_unit(design))
        assert again.params.model_dump(exclude={"family"}) == pytest.approx(design.params.model_dump(exclude={"family"}))


def test_to_unit_inverts_from_unit():
    """Exactly, wherever no range has collapsed to one value (a standing tube's grip height has: see the test above)."""
    space = SearchSpace(PARTS["cap"])

    for unit in corners_and_samples(len(space.names)):
        assert space.to_unit(space.from_unit(unit)) == pytest.approx(unit)


@pytest.mark.parametrize(
    "gripper", [Gripper(stroke_mm=10.0), Gripper(stroke_mm=3.0, free_space_mm=(30.0, 15.0))], ids=["long stroke", "cramped"]
)
def test_every_point_fits_another_gripper_too(gripper):
    part = PARTS["cap"]
    space = SearchSpace(part, gripper=gripper)

    for unit in corners_and_samples(len(space.names), seed=1, samples=10):
        design = space.from_unit(unit)
        assert problems(part, build_finger(part, design, gripper), gripper) == [], design.params


def test_a_longer_stroke_leaves_more_slack():
    def most_slack(gripper):
        return SearchSpace(PARTS["cube"], gripper=gripper).bounds()["slack_mm"][1]

    assert most_slack(Gripper(stroke_mm=10.0)) == pytest.approx(most_slack(Gripper()) + 4)


def test_a_deeper_groove_leaves_less_slack():
    space = SearchSpace(PARTS["cap"])
    shallow = space.from_unit([0.5, 0.2, 0.0, 1.0, 0.5, 0.5])
    deep = space.from_unit([0.5, 0.2, 1.0, 1.0, 0.5, 0.5])

    assert deep.params.groove_depth_mm > shallow.params.groove_depth_mm
    assert deep.params.slack_mm < shallow.params.slack_mm


def test_bounds_cover_every_free_parameter_and_keep_the_pad_beside_the_gripper():
    space = SearchSpace(PARTS["lying tube"])
    bounds = space.bounds()

    assert list(bounds) == space.names
    assert all(lo <= hi for lo, hi in bounds.values())
    assert bounds["pad_width_mm"][1] <= 58


def test_locks_drop_out_of_the_cube_and_ranges_bound_what_is_searched():
    choice = FamilyChoice(locks={"pad_width_mm": 20, "lead_in_mm": 1.0}, ranges={"slack_mm": ParamRange(lo=1, hi=2)})
    space = SearchSpace(PARTS["cap"], choice)

    assert space.names == ["groove_angle_deg", "groove_depth_mm", "slack_mm", "tip_height_mm"]
    for unit in corners_and_samples(4):
        p = space.from_unit(unit).params
        assert (p.pad_width_mm, p.lead_in_mm) == (20, 1.0)
        assert 1 - 1e-9 <= p.slack_mm <= 2 + 1e-9
    assert space.from_unit([0.5, 0.5, 0.0, 0.5]).params.slack_mm == pytest.approx(1)


def test_a_range_outside_the_limits_becomes_the_nearest_limit():
    space = SearchSpace(PARTS["cube"], FamilyChoice(ranges={"slack_mm": ParamRange(lo=20, hi=30)}))
    most = space._limits("slack_mm", {"pad_width_mm": 10.0, "groove_angle_deg": 180.0, "groove_depth_mm": 0.0}).hi

    assert {space.from_unit([0.5, u, 0.5, 0.5]).params.slack_mm for u in (0.0, 0.5, 1.0)} == {most}
    (slack,) = [s for s in space.describe() if s.name == "slack_mm"]
    assert slack.effective_range == (most, most)
    assert slack.note == f"slack 20-30 mm isn't buildable: using {most:g} mm (the stroke leaves no more)"


def test_a_user_range_can_reach_past_the_default_up_to_the_limits():
    """The default searches grips in the lower 60% of the part; a user may ask for higher, up to 2 mm of pad left."""
    space = SearchSpace(PARTS["cube"], FamilyChoice(ranges={"tip_height_mm": ParamRange(lo=5, hi=20)}))
    (tip,) = [s for s in space.describe() if s.name == "tip_height_mm"]

    assert tip.default_range == (1, 6) and tip.limits == (1, 8)
    assert tip.effective_range == (5, 8)
    assert tip.note == "tip height clipped to 8 mm: a higher grip leaves less than 2 mm of pad on the part"


def test_a_locked_value_is_clipped_into_the_limits_with_a_note():
    space = SearchSpace(PARTS["cube"], FamilyChoice(locks={"slack_mm": 50}))
    slack = {s.name: s for s in space.describe()}["slack_mm"]

    assert slack.locked == 50 and slack.effective_range == (5.5, 5.5)
    assert slack.note == "slack clipped to 5.5 mm: the stroke leaves no more"
    assert space.from_unit([0.5, 0.5, 0.5]).params.slack_mm == pytest.approx(5.5)


def test_locks_on_inapplicable_fields_are_ignored_with_a_note():
    space = SearchSpace(PARTS["cube"], FamilyChoice(locks={"groove_angle_deg": 90}))
    angle = {s.name: s for s in space.describe()}["groove_angle_deg"]

    assert not angle.applies and angle.effective_range == (180, 180)
    assert angle.note == "groove angle only applies to upright cylinders: fixed at 180 deg"
    assert space.from_unit([0.5] * 4).params.groove_angle_deg == 180


def test_a_fully_locked_family_is_a_single_design():
    locks = {"pad_width_mm": 9, "slack_mm": 2, "tip_height_mm": 3, "lead_in_mm": 1}
    space = SearchSpace(PARTS["cube"], FamilyChoice(locks=locks))

    assert space.names == []
    design = space.locked_design()
    assert design == space.centre() == Design(kind="locked", params=VPadParams(**locks))
    assert space.to_unit(design) == []
    with pytest.raises(ValueError, match="free parameters"):
        SearchSpace(PARTS["cube"]).locked_design()


def test_the_clearance_caps_the_pad_width_and_how_far_it_reaches():
    part, clearance = PARTS["cap"], 6.0
    space = SearchSpace(part, clearance_mm=clearance)

    for unit in corners_and_samples(len(space.names)):
        p = space.from_unit(unit).params
        assert p.pad_width_mm <= part.extent_mm[1] + 2 * clearance + 1e-9
        assert p.slack_mm + p.groove_depth_mm + p.lead_in_mm + WALL_MM <= clearance + 1e-9
        assert problems(part, build_finger(part, space.from_unit(unit)), clearance_mm=clearance) == [], p


def test_a_clearance_too_small_for_any_pad_says_so():
    space = SearchSpace(PARTS["cube"], clearance_mm=2.0)
    slack = {s.name: s for s in space.describe()}["slack_mm"]

    assert slack.note == "no slack fits: the part's clearance leaves no more (using 0.5 mm)"
    assert problems(PARTS["cube"], build_finger(PARTS["cube"], space.centre()), clearance_mm=2.0) != []


def test_describe_summarises_every_parameter_in_field_order():
    summaries = SearchSpace(PARTS["cap"]).describe()

    assert [s.name for s in summaries] == VPAD_FIELDS
    assert {s.unit for s in summaries} == {"mm", "deg"}
    assert all(s.applies and s.note is None and s.effective_range == s.default_range for s in summaries)
    assert all(s.limits[0] <= s.default_range[0] <= s.default_range[1] <= s.limits[1] for s in summaries)
