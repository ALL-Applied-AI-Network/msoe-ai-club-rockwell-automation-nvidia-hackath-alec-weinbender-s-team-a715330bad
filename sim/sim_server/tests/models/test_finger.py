import pytest
from pydantic import ValidationError

from sim_server.models.finger import FingerDesign, Piece

PIECE = Piece(points=((0, 0, 0), (0.01, 0, 0), (0, 0.01, 0), (0, 0, 0.01)), triangles=((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)))


def test_stock_design_has_no_finger_key():
    stock = FingerDesign(id="stock")
    assert stock.is_stock and stock.finger_key is None


def test_finger_key_identifies_geometry_and_friction_not_the_id_or_grasp():
    a = FingerDesign(id="a", pieces=(PIECE,), friction=(0.6, 0.5), tip_height=0.004, jaw_close=0.001)
    b = FingerDesign(id="b", pieces=(PIECE,), friction=(0.6, 0.5), tip_height=0.002, jaw_close=0.002)
    c = FingerDesign(id="c", pieces=(PIECE,), friction=(0.9, 0.8), tip_height=0.004, jaw_close=0.001)
    assert not a.is_stock
    assert a.finger_key == b.finger_key and hash(a.finger_key) == hash(b.finger_key)  # same fingers: no stage edit
    assert a.finger_key != c.finger_key


def test_designs_are_frozen():
    with pytest.raises(ValidationError):
        FingerDesign(id="stock").tip_height = 0.003
