"""The printable finger: the simulated convex solids (api/models/finger.py: finger_solids) fused into one body, with the
cell profile's mount features and the finger's engraved ID. None of these change the collision shape, so they exist only
here; export_check.py checks the result still matches what was simulated.

Same frame as finger.py: the gripper frame G, mm, jaws closed, fingertips at z = 0. The left finger ("L") is the one on the
+x jaw, with its blade at x 0..W, y -t/2..t/2, z 0..L (W, t, L = gripper.blade_mm); the right finger ("R") is its mirror
image in x.

Mount features are placed from the blade root (its top, z = L), as the profile measures them (cell_profile.FingerMount):

- holes go through the blade's thickness (along y), with a counterbore from each face when the profile gives one;
- locating pins are bosses standing out of the mount face (the face that sits against the jaw), and slots are cut into it;
- every printed hole (holes, counterbores, slot widths) gets gripper.hole_clearance_mm, since printed holes come out
  undersized. Pins don't: they're bosses, and their nominal size is what the jaw's hole expects.

The ID (D15) is engraved 0.4 mm deep on the face opposite the mount face, along the blade, between the bridge and the mount
features. That face is chosen over the outer x face because it's twice as wide (the blade's 12 mm width rather than its
6 mm thickness), so the text can be bigger, and because nothing touches it: the jaw is on the other side and the part is
gripped by the pad. Each side's text reads correctly from outside, with the tops of the letters toward the finger's outer
edge, so the left finger is built, mirrored for the right, and only then is each side's own text cut. If there's no room
for legible characters, or no font, the finger is still built, without text, and the engraved-id check says why.
"""

import logging
from dataclasses import dataclass
from typing import Literal

import cadquery as cq

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.finger import finger_solids
from api.models.part import Part

logger = logging.getLogger(__name__)

Side = Literal["L", "R"]

ENGRAVE_DEPTH_MM = 0.4  # D15: cut in, not embossed, so the text can't touch anything
MIN_CHAR_MM = 2.5  # smallest legible capital height on an FDM print
MAX_CHAR_MM = 5.0
TEXT_MARGIN_MM = 1.0  # clear of the bridge, the mount features and the blade's edges
ENGRAVE_FONT = "Arial"  # OpenCascade falls back to another installed font if this one is missing
ENGRAVE_KIND: Literal["regular", "bold"] = "bold"  # bold strokes stay wider than a 0.4 mm nozzle at small sizes
_PROUD_MM = 0.1  # the text cutter starts this far outside the face, so the cut has no coplanar faces
_REFERENCE_SIZE = 10.0  # font size the text is measured at before it's sized to fit


@dataclass(frozen=True)
class Engraving:
    """The finger's engraved ID, or why it has none. volume_mm3 is the material the text removed."""

    text: str | None
    detail: str
    volume_mm3: float = 0.0
    char_mm: float = 0.0


@dataclass(frozen=True)
class PrintableFinger:
    """One side's printable solid, in G as mounted with the jaws closed, plus what export_check.py and the print sheet
    need to know about it: the engraving, and what would overhang the bed in the print orientation (print_pose)."""

    side: Side
    solid: cq.Shape
    engraving: Engraving
    overhangs: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Body:
    shape: cq.Shape  # the left finger, fused, with its mount features
    text_floor_mm: float  # top of whatever is wider than the plain blade (the bridge): the text goes above it
    overhangs: tuple[str, ...]


def finger_solid(part: Part, design: Design, gripper: Gripper | None = None, *, finger_id: str | None = None, side: Side = "L") -> cq.Shape:
    """The printable finger for one side: what its STEP and STL hold. finger_id (e.g. EXP-0042-D1) is engraved with the
    side appended (EXP-0042-D1-L); None engraves nothing."""
    return printable_finger(part, design, gripper, finger_id=finger_id, side=side).solid


def printable_finger(
    part: Part, design: Design, gripper: Gripper | None = None, *, finger_id: str | None = None, side: Side = "L"
) -> PrintableFinger:
    """One side's printable finger, with what the checks and the print sheet need to know about it."""
    gripper = gripper or Gripper()
    return _finish(_body(part, design, gripper), gripper, finger_id, side)


def printable_pair(
    part: Part, design: Design, gripper: Gripper | None = None, *, finger_id: str | None = None
) -> tuple[PrintableFinger, PrintableFinger]:
    """Both sides, sharing one build of the body: the left, and the right mirrored from it, each with its own ID."""
    gripper = gripper or Gripper()
    body = _body(part, design, gripper)
    return _finish(body, gripper, finger_id, "L"), _finish(body, gripper, finger_id, "R")


def print_pose(finger: PrintableFinger) -> cq.Shape:
    """The finger as it should lie on the print bed: on its outer side (the face opposite the pad), so the pad face, its
    groove and its lead-in face up and print without supports. A rotation about y (the left finger's +x goes down, the
    right's -x), then moved so the bed is z = 0 and the part sits in the +x +y quadrant. A rotation, never a mirror, so
    the engraved ID still reads correctly."""
    turned = finger.solid.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), 90 if finger.side == "L" else -90)
    box = turned.BoundingBox()
    return turned.translate(cq.Vector(-box.xmin, -box.ymin, -box.zmin))


def print_orientation(finger: PrintableFinger) -> str:
    """The orientation advice for the print sheet, with a supports note when something overhangs the bed."""
    advice = (
        "Lie each finger on its outer side (the face opposite the pad), pad face up: the pad, its groove and its lead-in "
        "then print facing up with no supports. The STLs are already in this orientation."
    )
    if finger.overhangs:
        advice += f" Supports needed: {'; '.join(finger.overhangs)}. Use supports from the build plate only, away from the pad face."
    else:
        advice += " Nothing overhangs the bed: no supports."
    return advice


def _body(part: Part, design: Design, gripper: Gripper) -> _Body:
    if design.kind == "stock":
        raise ValueError("the stock fingers are aluminium and already on the robot: there's nothing to print")
    solids = finger_solids(part, design, gripper)
    root = gripper.blade_mm[2]
    boxes = [s.BoundingBox() for s in solids]
    floor = max((b.zmax for b in boxes if b.zmax < root - 1e-6), default=0.0)
    shape = solids[0].fuse(*solids[1:]).clean()
    if cutters := _mount_cutters(gripper):
        shape = shape.cut(*cutters)
    if bosses := _mount_bosses(gripper):
        shape = shape.fuse(*bosses).clean()
    return _Body(shape, floor, _overhangs(boxes, root, pins=any(f.kind == "pin" for f in gripper.mount.locating)))


def _mount_cutters(gripper: Gripper) -> list[cq.Solid]:
    """Holes (through the blade's thickness, along y) with their counterbores, and the locating slots in the mount face."""
    _, t, root = gripper.blade_mm
    clearance, face = gripper.hole_clearance_mm, _mount_sign(gripper)
    out = []
    for hole in gripper.mount.holes:
        x, z = hole.x_mm, root - hole.below_root_mm
        out.append(_cylinder((hole.diameter_mm + clearance) / 2, (x, -t / 2 - 1.0, z), (0, 1, 0), t + 2.0))
        if hole.counterbore_diameter_mm:
            depth = min(hole.counterbore_depth_mm, t / 2)
            for sign in (1, -1):
                start = (x, sign * (t / 2 - depth), z)
                out.append(_cylinder((hole.counterbore_diameter_mm + clearance) / 2, start, (0, sign, 0), depth + 1.0))
    for slot in gripper.mount.locating:
        if slot.kind != "slot":
            continue
        width = slot.diameter_mm + clearance
        length = max(slot.length_mm, width)  # end to end, along the blade
        plane = cq.Plane(origin=(slot.x_mm, face * (t / 2 + 1.0), root - slot.below_root_mm), xDir=(0, 0, 1), normal=(0, -face, 0))
        sketch = cq.Workplane(plane)
        sketch = sketch.slot2D(length, width) if length > width else sketch.circle(width / 2)
        out.append(sketch.extrude(slot.height_mm + 1.0).val())
    return out


def _mount_bosses(gripper: Gripper) -> list[cq.Solid]:
    """Locating pins: cylinders standing height_mm out of the mount face (rooted 0.5 mm inside it, so they fuse cleanly)."""
    _, t, root = gripper.blade_mm
    face = _mount_sign(gripper)
    return [
        _cylinder(pin.diameter_mm / 2, (pin.x_mm, face * (t / 2 - 0.5), root - pin.below_root_mm), (0, face, 0), pin.height_mm + 0.5)
        for pin in gripper.mount.locating
        if pin.kind == "pin"
    ]


def _mount_sign(gripper: Gripper) -> int:
    """+1 if the blade's +y face sits against the jaw, -1 for its -y face."""
    return 1 if gripper.mount.face == "+y" else -1


def _cylinder(radius: float, start: tuple[float, float, float], direction: tuple[float, float, float], length: float) -> cq.Solid:
    return cq.Solid.makeCylinder(radius, length, pnt=cq.Vector(*start), dir=cq.Vector(*direction))


def _overhangs(boxes: list[cq.BoundBox], root: float, pins: bool) -> tuple[str, ...]:
    """What hangs above the bed when the finger lies on its outer side: any convex solid whose outer x face stops short
    of the outermost one (the blade, when the pad is set further out than it; the pad, when the bridge reaches past it)."""
    bed = max(b.xmax for b in boxes)
    lifted: dict[str, tuple[float, float, float]] = {}
    for b in boxes:
        lift = bed - b.xmax
        if lift <= 0.05:
            continue
        name = "the blade" if b.zmax >= root - 1e-6 else "the pad" if b.zmin <= 1e-6 else "the bridge"
        old = lifted.get(name, (0.0, b.zmin, b.zmax))
        lifted[name] = (max(old[0], lift), min(old[1], b.zmin), max(old[2], b.zmax))
    notes = [
        f"{name} sits {lift:.1f} mm above the bed (z {lo:.1f} to {hi:.1f} mm along the finger)" for name, (lift, lo, hi) in lifted.items()
    ]
    if pins:
        notes.append("the locating pins print sideways, so check they come out round")
    return tuple(notes)


def _finish(body: _Body, gripper: Gripper, finger_id: str | None, side: Side) -> PrintableFinger:
    shape = body.shape if side == "L" else body.shape.mirror("YZ")
    if finger_id is None:
        return PrintableFinger(side, shape, Engraving(None, "no finger ID was given to engrave"), body.overhangs)
    shape, engraving = _engrave(shape, f"{finger_id}-{side}", side, body.text_floor_mm, gripper)
    return PrintableFinger(side, shape, engraving, body.overhangs)


def _engrave(shape: cq.Shape, text: str, side: Side, floor: float, gripper: Gripper) -> tuple[cq.Shape, Engraving]:
    """Cut the text into the face opposite the mount face, centred in the free stretch of blade between the bridge and the
    mount features, as large as fits up to MAX_CHAR_MM. Never raises: a finger without its ID still prints and bolts on."""
    width, t, root = gripper.blade_mm
    lo, hi = floor + TEXT_MARGIN_MM, _features_bottom(gripper) - TEXT_MARGIN_MM
    normal_y = -_mount_sign(gripper)
    face = "+y" if normal_y > 0 else "-y"
    try:
        flat = cq.Compound.makeText(text, _REFERENCE_SIZE, 0.0, font=ENGRAVE_FONT, kind=ENGRAVE_KIND)
        box, area = flat.BoundingBox(), flat.Area()
    except Exception as e:  # OpenCascade raises its own types, or fails on None, when it finds no font at all
        logger.warning("can't engrave %s: no usable font (%s)", text, e)
        return shape, Engraving(None, f"skipped: no font for the text ({type(e).__name__})")
    if box.xlen <= 0 or box.ylen <= 0:
        return shape, Engraving(None, "skipped: the font produced no outlines")
    length_per_size, char_per_size = box.xlen / _REFERENCE_SIZE, box.ylen / _REFERENCE_SIZE
    room = max(0.0, hi - lo)
    size = min(MAX_CHAR_MM / char_per_size, room / length_per_size, (width - 2 * TEXT_MARGIN_MM) / char_per_size)
    char = size * char_per_size
    if char < MIN_CHAR_MM:
        return shape, Engraving(
            None,
            f"skipped: no room for legible text: the blade leaves {room:.1f} mm between the bridge (z {floor:.1f}) and the "
            f"mount features (z {hi + TEXT_MARGIN_MM:.1f}), so {len(text)} characters would be {char:.1f} mm tall; "
            f"they need {MIN_CHAR_MM:g} mm",
        )
    out = 1.0 if side == "L" else -1.0  # the finger's outer edge, where the tops of the letters point
    up, normal = cq.Vector(out, 0, 0), cq.Vector(0, normal_y, 0)
    x_dir = up.cross(normal)  # reading direction: along the blade, so the text reads correctly from outside the face
    centre = cq.Vector(out * width / 2, normal_y * t / 2, (lo + hi) / 2)
    scale = size / _REFERENCE_SIZE
    origin = centre + normal * _PROUD_MM - x_dir * (box.center.x * scale) - up * (box.center.y * scale)
    try:
        plane = cq.Plane(origin=origin, xDir=x_dir, normal=normal)
        cutter = cq.Compound.makeText(text, size, -(ENGRAVE_DEPTH_MM + _PROUD_MM), font=ENGRAVE_FONT, kind=ENGRAVE_KIND, position=plane)
        cut = shape.cut(cutter)
        if len(cut.Solids()) != 1:
            raise ValueError(f"the cut left {len(cut.Solids())} solids")
    except Exception as e:
        logger.warning("can't engrave %s: %s", text, e)
        return shape, Engraving(None, f"skipped: the engraving cut failed ({e})")
    removed = area * scale**2 * ENGRAVE_DEPTH_MM  # a prism of the letters' outline, as deep as it reaches into the face
    z0, z1 = (lo + hi) / 2 - size * length_per_size / 2, (lo + hi) / 2 + size * length_per_size / 2
    detail = f"{text}: {char:.1f} mm capitals, {ENGRAVE_DEPTH_MM:g} mm deep, on the blade's {face} face at z {z0:.1f} to {z1:.1f} mm"
    return cut, Engraving(text, detail, removed, char)


def _features_bottom(gripper: Gripper) -> float:
    """The lowest point of any mount feature that reaches the text's face: holes, counterbores and slots (pins stand on
    the other face). The blade root if there are none."""
    root, clearance = gripper.blade_mm[2], gripper.hole_clearance_mm
    bottoms = [root]
    for hole in gripper.mount.holes:
        widest = max(hole.diameter_mm, hole.counterbore_diameter_mm or 0.0) + clearance
        bottoms.append(root - hole.below_root_mm - widest / 2)
    for slot in gripper.mount.locating:
        if slot.kind == "slot":
            bottoms.append(root - slot.below_root_mm - max(slot.length_mm, slot.diameter_mm + clearance) / 2)
    return min(bottoms)
