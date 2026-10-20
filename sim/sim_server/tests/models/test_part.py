import pytest
from pydantic import ValidationError

from sim_server.models.part import Part


def test_width_and_height_follow_the_nominal_frame():
    lying = Part(shape="cylinder", size=(0.010, 0.020, 0.010), mass=0.003, cylinder_axis="y")
    assert lying.width == 0.010 and lying.height == 0.010


def test_parts_are_frozen_values():
    part = Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)
    assert part == Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)  # equal parts need no stage edit
    with pytest.raises(ValidationError):
        part.mass = 0.005
    with pytest.raises(ValidationError):
        Part(shape="sphere", size=(0.01, 0.01, 0.01), mass=0.004)
