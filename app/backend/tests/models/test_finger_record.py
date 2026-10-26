import pytest

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.family import VPadParams
from api.models.finger import SQUEEZE_MM, STOCK_TIP_MM, build_finger, problems, seat
from api.models.finger_record import FingerRecord, finger_code
from api.models.part import Part
from api.models.piece import hull_piece

GRIPPER = Gripper()
CUBE = Part(shape="box")  # 10 mm


def blade(x0: float = 0.0, width: float = 12.0, depth: float = 6.0, length: float = 76.0):
    """A flat blade in the gripper frame: its gripping face at x0, fingertips at z = 0."""
    return [hull_piece([(x, y, z) for x in (x0, x0 + width) for y in (-depth / 2, depth / 2) for z in (0.0, length)])]


def record(**values) -> FingerRecord:
    base = {"id": "f1", "number": 7, "name": "a finger", "created": 0.0, "source": "uploaded", "cell_profile_name": "cell"}
    return FingerRecord(**{**base, "family": "flat", "pad_friction": (0.6, 0.5), **values})


def test_seat_closes_the_jaws_until_the_face_meets_the_part():
    finger = seat(blade(), CUBE, GRIPPER)

    # the face at x = 0 meets a 10 mm cube with the jaw 5 mm out; then it squeezes
    assert finger.jaw_close_mm == pytest.approx(5 - SQUEEZE_MM, abs=0.02)
    assert finger.tip_height_mm == STOCK_TIP_MM and finger.contact_mm == pytest.approx(10 - STOCK_TIP_MM)
    assert problems(CUBE, finger, GRIPPER) == []


def test_seat_follows_a_face_set_back_from_the_jaw():
    assert seat(blade(x0=2.0), CUBE, GRIPPER).jaw_close_mm == pytest.approx(3 - SQUEEZE_MM, abs=0.02)


def test_seat_says_when_a_finger_lands_on_the_part_or_never_reaches_it():
    lands = seat(blade(x0=-3.0), Part(shape="box", width_mm=10), GRIPPER)  # open, the face is at 3 mm: inside the part
    misses = seat(blade(x0=6.0), Part(shape="box", width_mm=4), GRIPPER)  # closed, the face is 6 mm out: the part is 2

    assert lands.jaw_close_mm == pytest.approx(GRIPPER.stroke_mm)
    assert any("land on the centred part" in p for p in problems(CUBE, lands, GRIPPER))
    assert misses.jaw_close_mm == pytest.approx(-SQUEEZE_MM)
    assert any("can't reach the gripping position" in p for p in problems(Part(shape="box", width_mm=4), misses, GRIPPER))


def test_seat_takes_a_locked_grip_height():
    finger = seat(blade(), CUBE, GRIPPER, tip_height_mm=4.0)

    assert finger.tip_height_mm == 4.0 and finger.contact_mm == pytest.approx(6.0)


def test_an_uploaded_finger_grips_through_seat_with_its_own_friction():
    finger = record(pieces=blade(), pad_friction=(0.9, 0.8)).grip(CUBE, GRIPPER)

    assert finger.friction == (0.9, 0.8) and finger.jaw_close_mm == pytest.approx(5 - SQUEEZE_MM, abs=0.02)


def test_a_generated_finger_keeps_its_pads_and_reseats_on_another_part():
    design = Design(params=VPadParams(pad_width_mm=10, slack_mm=1, tip_height_mm=2))
    generated = record(source="generated", family="vpad", built_for=CUBE, design=design)
    wider = Part(shape="box", width_mm=11)

    own, other = generated.grip(CUBE, GRIPPER), generated.grip(wider, GRIPPER)

    built = build_finger(CUBE, design, GRIPPER)
    assert other.pieces == own.pieces == built.pieces, "the same physical finger"
    assert other.jaw_close_mm == pytest.approx(own.jaw_close_mm + 0.5), "a part 1 mm wider seats 0.5 mm further out per jaw"
    assert problems(wider, other, GRIPPER) == []


def test_the_stock_fingers_are_the_robots_own():
    stock = record(source="stock", family="stock")

    assert stock.grip(CUBE, GRIPPER) is None and stock.geometry(GRIPPER) is None


def test_the_code_is_the_fixed_number():
    assert record().code == finger_code(7) == "FNG-0007"
