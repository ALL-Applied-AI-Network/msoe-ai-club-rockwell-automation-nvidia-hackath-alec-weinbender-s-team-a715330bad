import cadquery as cq
import pytest

from api.models import finger_cad
from api.models.cell_profile import PHOTO_MOUNT, SMC_FLAT_JAW_MOUNT, FingerMount, Gripper, LocatingFeature, MountHole
from api.models.design import Design
from api.models.finger_cad import ENGRAVE_DEPTH_MM, MIN_CHAR_MM, finger_solid, print_pose, printable_finger, printable_pair
from api.models.part import Part

CAP = Part()
VPAD = Design(params={"pad_width_mm": 20, "groove_angle_deg": 90, "groove_depth_mm": 3, "slack_mm": 3, "tip_height_mm": 4, "lead_in_mm": 1})
FLAT = Design(params={"pad_width_mm": 8, "slack_mm": 3, "tip_height_mm": 4})
GRIPPER = Gripper()  # SMC's jaw: SMC_FLAT_JAW_MOUNT
PHOTO = Gripper(mount=PHOTO_MOUNT)  # the twin's photo reconstruction: holes through the blade's thickness


def font_available() -> bool:
    try:
        return cq.Compound.makeText("A", 5.0, 0.0).BoundingBox().xlen > 0
    except Exception:
        return False


def radii(shape: cq.Shape) -> set[float]:
    """The radii of the solid's circular edges: the holes' and counterbores' rims (the text's outlines are B-splines)."""
    return {round(edge.radius(), 4) for edge in shape.Edges() if edge.geomType() == "CIRCLE"}


def centroid_offset(shape: cq.Shape, reading: cq.Vector, up: cq.Vector) -> tuple[float, float]:
    """Where a text's area centroid sits relative to its bounding box centre, as fractions of its length (along the reading
    direction) and height (along up). Text reads correctly when these match the same text laid flat on XY, seen from +z;
    mirrored text flips one of them."""
    box = shape.BoundingBox()
    d = shape.Center() - box.center
    extent = cq.Vector(box.xlen, box.ylen, box.zlen)
    return d.dot(reading) / abs(extent.dot(reading)), d.dot(up) / abs(extent.dot(up))


@pytest.fixture(scope="module")
def pair():
    return printable_pair(CAP, VPAD, GRIPPER, finger_id="EXP-0042-D1")


def test_each_side_is_one_valid_solid_and_the_right_is_the_lefts_mirror(pair):
    left, right = pair

    assert (left.side, right.side) == ("L", "R")
    for finger in pair:
        assert len(finger.solid.Solids()) == 1 and finger.solid.isValid()
    lb, rb = left.solid.BoundingBox(), right.solid.BoundingBox()
    assert (rb.xmin, rb.xmax) == pytest.approx((-lb.xmax, -lb.xmin), abs=1e-6)
    assert (rb.ymin, rb.ymax, rb.zmin, rb.zmax) == pytest.approx((lb.ymin, lb.ymax, lb.zmin, lb.zmax), abs=1e-6)
    assert lb.zmin == pytest.approx(0, abs=1e-6) and lb.zmax == pytest.approx(GRIPPER.blade_mm[2])


def test_mount_holes_and_counterbores_are_printed_with_the_hole_clearance():
    hole = PHOTO.mount.holes[0]
    loose = Gripper(mount=PHOTO_MOUNT, hole_clearance_mm=0.4)

    for gripper in (PHOTO, loose):
        printed = {round((d + gripper.hole_clearance_mm) / 2, 4) for d in (hole.diameter_mm, hole.counterbore_diameter_mm)}
        assert radii(finger_solid(CAP, VPAD, gripper)) == printed
    assert round(hole.diameter_mm / 2, 4) not in radii(finger_solid(CAP, VPAD, PHOTO)), (
        "a printed hole at its nominal size comes out too tight"
    )


def test_the_smc_jaw_mount_cuts_the_root_back_to_the_jaws_face_and_drills_along_x(pair):
    mount, (width, _, root) = SMC_FLAT_JAW_MOUNT, GRIPPER.blade_mm
    solid = pair[0].solid
    step = mount.jaw_length_mm + mount.jaw_clearance_mm

    def x_reach(z0: float, z1: float) -> float:
        return solid.intersect(cq.Solid.makeBox(40, 40, z1 - z0, pnt=cq.Vector(-20, -20, z0))).BoundingBox().xmax

    assert x_reach(root - step + 0.5, root - 0.5) == pytest.approx(mount.face_x_mm, abs=1e-6), "the root stops at the jaw's face"
    assert x_reach(root - step - 5.0, root - step - 0.5) == pytest.approx(width, abs=1e-6), "the full blade below the jaw"
    printed = (mount.holes[0].diameter_mm + GRIPPER.hole_clearance_mm) / 2
    rims = [e for e in solid.Edges() if e.geomType() == "CIRCLE"]
    assert {round(e.radius(), 4) for e in rims} == {round(printed, 4)}
    # Each hole's rim on the jaw's face and its floor 6 mm in, centred on the blade's mid-plane, along x.
    centres = sorted((round(c.x, 3), round(c.y, 3), round(c.z, 3)) for c in (e.arcCenter() for e in rims))
    holes = [root - hole.below_root_mm for hole in mount.holes]
    assert centres == sorted((round(x, 3), 0.0, round(z, 3)) for z in holes for x in (mount.face_x_mm, mount.face_x_mm - 6.0))


def test_a_mount_that_doesnt_fit_its_face_or_blade_is_refused():
    pin = LocatingFeature(kind="pin", below_root_mm=4, x_mm=3, diameter_mm=2)

    with pytest.raises(ValueError, match="only modelled on a"):
        FingerMount(locating=[pin])
    with pytest.raises(ValueError, match="have no depth"):
        FingerMount(face="-y", holes=[MountHole(below_root_mm=10, depth_mm=4)])
    with pytest.raises(ValueError, match="past the end of the jaw"):
        FingerMount(holes=[MountHole(below_root_mm=23, diameter_mm=2.5, counterbore_diameter_mm=None)])
    with pytest.raises(ValueError, match="can't have a counterbore"):
        FingerMount(holes=[MountHole(below_root_mm=4, depth_mm=6)])
    with pytest.raises(ValueError, match="outside the 6 mm blade"):
        Gripper(blade_mm=(6, 12, 76))
    with pytest.raises(ValueError, match="past the 10 mm kept as stock"):
        Gripper(mount_kept_mm=10)
    assert Gripper(blade_mm=(6, 12, 76), mount=PHOTO_MOUNT).mount.face == "-y"


def test_the_id_is_engraved_on_each_side_reading_correctly(pair):
    if not font_available():
        pytest.skip("no font installed for CadQuery's text")
    left, right = pair
    plain = finger_solid(CAP, VPAD, GRIPPER)

    assert left.engraving.text == "EXP-0042-D1-L" and right.engraving.text == "EXP-0042-D1-R"
    for finger in pair:
        assert finger.engraving.char_mm >= MIN_CHAR_MM
        assert plain.Volume() - finger.solid.Volume() == pytest.approx(finger.engraving.volume_mm3, rel=1e-3)
    # Engraved, not embossed: the text stays inside the blade, ENGRAVE_DEPTH_MM into its +y face (the face opposite the jaw).
    assert left.solid.BoundingBox().ymax == pytest.approx(plain.BoundingBox().ymax)
    text = plain.cut(left.solid)
    box = text.BoundingBox()
    assert box.ymax == pytest.approx(GRIPPER.blade_mm[1] / 2, abs=1e-3)
    assert box.ymin == pytest.approx(GRIPPER.blade_mm[1] / 2 - ENGRAVE_DEPTH_MM, abs=1e-3)
    assert 0 < box.xmin and box.xmax < GRIPPER.blade_mm[0], "on the blade, clear of its edges"


def test_each_sides_text_reads_correctly_from_outside_not_mirrored():
    """Seen from outside the +y face with the finger's outer edge up, each side's text must read left to right like the
    same text laid flat. "TTTT" makes the text lopsided both along it and across it, so a mirrored or reversed engraving
    can't pass by symmetry."""
    if not font_available():
        pytest.skip("no font installed for CadQuery's text")
    normal = cq.Vector(0, 1, 0)
    for finger in printable_pair(CAP, VPAD, GRIPPER, finger_id="TTTT"):
        up = cq.Vector(1 if finger.side == "L" else -1, 0, 0)  # the finger's outer edge
        reading = up.cross(normal)  # left to right, for someone facing the +y face with the outer edge up
        text = finger_solid(CAP, VPAD, GRIPPER, side=finger.side).cut(finger.solid)
        flat = cq.Compound.makeText(finger.engraving.text, 10.0, 0.0, kind=finger_cad.ENGRAVE_KIND)

        expected = centroid_offset(flat, cq.Vector(1, 0, 0), cq.Vector(0, 1, 0))
        assert abs(expected[0]) > 0.015 and abs(expected[1]) > 0.05, "the probe text isn't lopsided enough to tell"
        assert centroid_offset(text, reading, up) == pytest.approx(expected, abs=0.005), finger.side


def test_with_the_mount_on_the_plus_y_face_the_text_moves_to_the_minus_y_face():
    if not font_available():
        pytest.skip("no font installed for CadQuery's text")
    gripper = Gripper(mount=FingerMount(face="+y", holes=PHOTO_MOUNT.holes))
    finger = printable_finger(CAP, VPAD, gripper, finger_id="EXP-0042-D1")
    box = finger_solid(CAP, VPAD, gripper).cut(finger.solid).BoundingBox()

    assert "-y face" in finger.engraving.detail
    assert box.ymin == pytest.approx(-GRIPPER.blade_mm[1] / 2, abs=1e-3)


def test_no_room_for_legible_text_skips_the_engraving_but_still_builds_the_finger():
    tall = Part(shape="box", height_mm=40)
    finger = printable_finger(tall, FLAT, GRIPPER, finger_id="EXP-0042-D1")

    assert finger.engraving.text is None and finger.engraving.volume_mm3 == 0
    assert finger.engraving.detail.startswith("skipped: no room for legible text")
    assert finger.solid.isValid() and len(finger.solid.Solids()) == 1


def test_no_font_skips_the_engraving_instead_of_raising(monkeypatch):
    def no_font(*args, **kwargs):
        raise AttributeError("'NoneType' object has no attribute 'FontName'")  # what CadQuery raises with no font at all

    monkeypatch.setattr(finger_cad.cq.Compound, "makeText", no_font)
    finger = printable_finger(CAP, VPAD, GRIPPER, finger_id="EXP-0042-D1", side="R")

    assert finger.engraving.text is None
    assert finger.engraving.detail.startswith("skipped: no font")
    assert finger.solid.isValid()


def test_locating_pins_stand_out_of_the_mount_face_and_slots_are_cut_into_it():
    pin = LocatingFeature(kind="pin", below_root_mm=4, x_mm=3, diameter_mm=2, height_mm=1.5)
    slot = LocatingFeature(kind="slot", below_root_mm=4, x_mm=9, diameter_mm=2, length_mm=5, height_mm=1)
    plain = finger_solid(CAP, FLAT, PHOTO)  # an 8 mm pad, so the pin stands out past everything else in -y
    with_pin = finger_solid(CAP, FLAT, Gripper(mount=FingerMount(face="-y", holes=PHOTO_MOUNT.holes, locating=[pin])))
    with_slot = finger_solid(CAP, FLAT, Gripper(mount=FingerMount(face="-y", holes=PHOTO_MOUNT.holes, locating=[slot])))

    assert with_pin.BoundingBox().ymin == pytest.approx(-GRIPPER.blade_mm[1] / 2 - pin.height_mm, abs=1e-3)
    assert with_pin.Volume() - plain.Volume() == pytest.approx(3.14159 * 1.5, rel=1e-3)
    assert with_slot.BoundingBox().ymin == pytest.approx(plain.BoundingBox().ymin)
    assert with_slot.Volume() < plain.Volume()


def test_a_profile_without_counterbores_drills_plain_holes():
    gripper = Gripper(mount=FingerMount(face="-y", holes=[MountHole(below_root_mm=10, x_mm=6, counterbore_diameter_mm=None)]))
    solid = finger_solid(CAP, VPAD, gripper)

    assert radii(solid) == {round((3.2 + gripper.hole_clearance_mm) / 2, 4)}


def test_the_print_pose_lies_on_the_outer_side_with_the_pad_face_up(pair):
    for finger in pair:
        original = finger.solid.BoundingBox()
        posed = print_pose(finger)
        box = posed.BoundingBox()

        assert (box.xmin, box.ymin, box.zmin) == pytest.approx((0, 0, 0), abs=1e-6)
        assert box.zlen == pytest.approx(original.xlen, abs=1e-6), "lying across the jaws: the finger's x is the height"
        assert box.xlen == pytest.approx(original.zlen, abs=1e-6), "the blade lies along the bed"
        assert posed.Volume() == pytest.approx(finger.solid.Volume()), "a rotation, not a mirror"
        # The outermost face (x = max on the left, x = min on the right) is the one on the bed.
        bed = [f for f in posed.Faces() if f.geomType() == "PLANE" and abs(f.Center().z) < 1e-6]
        assert bed and all(f.normalAt().z == pytest.approx(-1) for f in bed)


def test_overhangs_name_the_blade_when_the_pad_is_set_out_past_it(pair):
    assert any(note.startswith("the blade sits") for note in pair[0].overhangs)
    assert any(note.startswith("the root, cut back for the jaw, sits") for note in pair[0].overhangs)
    assert not any(note.startswith("the root") for note in printable_finger(CAP, VPAD, PHOTO).overhangs)
    cube = printable_finger(Part(shape="box"), FLAT, GRIPPER)
    assert any(note.startswith("the pad sits") for note in cube.overhangs)


def test_the_stock_fingers_cant_be_printed():
    with pytest.raises(ValueError, match="stock"):
        finger_solid(CAP, Design(kind="stock"), GRIPPER)
