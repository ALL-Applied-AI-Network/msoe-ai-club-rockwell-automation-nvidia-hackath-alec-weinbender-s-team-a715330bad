import random

import pytest

from api.models.design import PARAMS
from api.models.finger import build_finger, problems
from api.models.part import Part
from api.models.search_space import SearchSpace

PARTS = {"cap": Part(), "cube": Part(shape="box"), "lying tube": Part(diameter_mm=17, length_mm=140, upright=False)}


def test_grooves_are_searched_only_for_parts_round_from_above():
    assert SearchSpace(PARTS["cap"]).names == list(PARAMS)
    assert SearchSpace(PARTS["cube"]).names == ["pad_width_mm", "slack_mm", "tip_height_mm", "lead_in_mm"]


@pytest.mark.parametrize("part", PARTS.values(), ids=PARTS.keys())
def test_every_point_of_the_unit_cube_is_a_finger_that_fits(part):
    space, rng = SearchSpace(part), random.Random(0)
    corners = [[0.0] * len(space.names), [1.0] * len(space.names)]

    for unit in corners + [[rng.random() for _ in space.names] for _ in range(40)]:
        design = space.from_unit(unit)
        assert problems(part, build_finger(part, design)) == [], design.params
        assert space.to_unit(design) == pytest.approx(unit)


def test_a_deeper_groove_leaves_less_slack():
    space = SearchSpace(PARTS["cap"])
    shallow = space.from_unit([0.5, 0.2, 0.0, 1.0, 0.5, 0.5])
    deep = space.from_unit([0.5, 0.2, 1.0, 1.0, 0.5, 0.5])

    assert deep.params["groove_depth_mm"] > shallow.params["groove_depth_mm"]
    assert deep.params["slack_mm"] < shallow.params["slack_mm"]


def test_bounds_cover_every_parameter_and_keep_the_pad_beside_the_gripper():
    bounds = SearchSpace(PARTS["lying tube"]).bounds()

    assert list(bounds) == SearchSpace(PARTS["lying tube"]).names
    assert all(lo <= hi for lo, hi in bounds.values())
    assert bounds["pad_width_mm"][1] <= 58
