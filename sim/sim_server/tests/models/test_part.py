import pytest
from pydantic import ValidationError

from sim_server.models.part import Part
from sim_server.models.piece import Piece

PIECE = Piece(points=((0, 0, 0), (0.01, 0, 0), (0, 0.01, 0), (0, 0, 0.01)), triangles=((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)))


def test_width_and_height_follow_the_nominal_frame():
    lying = Part(shape="cylinder", size=(0.010, 0.020, 0.010), mass=0.003, cylinder_axis="y")
    assert lying.width == 0.010 and lying.height == 0.010


@pytest.mark.parametrize(
    ("axis", "size"),
    [("z", (0.010, 0.010, 0.020)), ("y", (0.010, 0.020, 0.010)), ("x", (0.020, 0.010, 0.010))],
)
def test_cylinder_length_and_diameter_follow_its_axis(axis, size):
    cylinder = Part(shape="cylinder", size=size, mass=0.003, cylinder_axis=axis)
    assert cylinder.length == 0.020 and cylinder.diameter == 0.010


def test_parts_are_frozen_values():
    part = Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)
    assert part == Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)  # equal parts need no stage edit
    with pytest.raises(ValidationError):
        part.mass = 0.005
    with pytest.raises(ValidationError):
        Part(shape="sphere", size=(0.01, 0.01, 0.01), mass=0.004)


def test_friction_makes_a_different_part():
    """The cell re-authors the stage (and the part's material) whenever the part changes, friction included."""
    plain = Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004)
    assert plain.friction is None
    assert Part(shape="box", size=(0.01, 0.01, 0.01), mass=0.004, friction=(0.4, 0.3)) != plain


def test_mesh_parts_carry_their_pieces():
    mesh = Part(shape="mesh", size=(0.01, 0.01, 0.01), mass=0.002, pieces=(PIECE,))
    assert mesh.pieces == (PIECE,) and mesh.width == 0.01
    assert mesh == Part(shape="mesh", size=(0.01, 0.01, 0.01), mass=0.002, pieces=(PIECE,))


@pytest.mark.parametrize(
    "fields",
    [
        {"shape": "cylinder"},  # no axis
        {"shape": "box", "cylinder_axis": "z"},
        {"shape": "mesh"},  # no pieces
        {"shape": "mesh", "pieces": ()},
        {"shape": "box", "pieces": (PIECE,)},
    ],
)
def test_shape_specific_fields_must_match_the_shape(fields):
    with pytest.raises(ValidationError):
        Part(size=(0.01, 0.01, 0.01), mass=0.004, **fields)
