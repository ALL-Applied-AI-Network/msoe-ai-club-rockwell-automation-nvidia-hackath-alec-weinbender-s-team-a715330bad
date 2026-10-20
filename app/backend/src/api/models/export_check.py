"""Checks a printable finger passes before it can be downloaded: every exported finger must print and bolt onto the real
gripper first time. A failed blocking check stops the download and says which check failed and by how much.

The checks compare the printable solids (finger_cad.py) against what was simulated (finger.py: build_finger's pieces).
What the mount features and the engraving add or remove is worked out from their dimensions alone, so a boolean that went
wrong, or pieces that overlap, show up as a mismatch instead of being trusted.

job.py and the database tables import ExportCheck, so this module doesn't load the CAD kernel itself: the solids arrive
already built, and build_finger is imported only when the checks run.
"""

import math
from collections.abc import Sequence
from itertools import combinations
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

from api.models.cell_profile import Gripper
from api.models.design import Design
from api.models.part import Part
from api.models.piece import Piece, pieces_bounds

if TYPE_CHECKING:
    from api.models.finger_cad import PrintableFinger

MIN_WALL_MM = 1.2  # two 0.4 mm nozzle lines plus margin: anything thinner prints weak or not at all
VOLUME_TOLERANCE = 0.005  # relative
BOX_TOLERANCE_MM = 0.05

Box = tuple[tuple[float, float, float], tuple[float, float, float]]


class ExportCheck(BaseModel):
    name: str  # "solid", "matches sim", "min wall", "finger length", "engraved id"
    ok: bool
    blocking: bool  # True: a failure blocks the download; False: a note (e.g. a check skipped while a value is unknown)
    detail: str  # with the numbers: "thinnest wall 0.9 mm beside the groove; needs 1.2 mm"


def run_checks(part: Part, design: Design, gripper: Gripper | None, fingers: Sequence["PrintableFinger"]) -> list[ExportCheck]:
    """Every export check, for the printable fingers of one design (both sides, from finger_cad.printable_pair)."""
    from api.models.finger import build_finger  # here, not at the top: see the module docstring

    gripper = gripper or Gripper()
    pieces = build_finger(part, design, gripper).pieces
    return [
        check_solid(fingers),
        check_matches_sim(pieces, gripper, fingers),
        check_min_wall(pieces, gripper),
        check_finger_length(gripper, fingers),
        check_engraved_id(fingers),
    ]


def check_solid(fingers: Sequence["PrintableFinger"]) -> ExportCheck:
    """Each side is exactly one valid solid (OpenCascade's BRepCheck) with a closed shell: what a slicer needs."""
    problems = []
    for finger in fingers:
        n = len(finger.solid.Solids())
        if n != 1:
            problems.append(f"{finger.side}: {n} solids, needs exactly 1")
        if not finger.solid.isValid():
            problems.append(f"{finger.side}: not a valid solid (BRepCheck failed)")
        if open_shells := sum(not shell.Closed() for shell in finger.solid.Shells()):
            problems.append(f"{finger.side}: {open_shells} open shell(s)")
    sides = " and ".join(finger.side for finger in fingers)
    return ExportCheck(name="solid", ok=not problems, blocking=True, detail="; ".join(problems) or f"{sides}: one valid, closed solid each")


def check_matches_sim(pieces: Sequence[Piece], gripper: Gripper, fingers: Sequence["PrintableFinger"]) -> ExportCheck:
    """Volume and bounding box against the simulated pieces: the solid's volume must be the pieces' volume, minus the
    holes, slots and engraving, plus the pins (within VOLUME_TOLERANCE), and its box the pieces' box grown by the pins
    (within BOX_TOLERANCE_MM). The right finger is compared with the pieces mirrored in x."""
    simulated = sum(_volume(piece) for piece in pieces)
    removed, added = mount_feature_volumes(gripper)
    lo, hi = pieces_bounds(pieces)
    for pin_lo, pin_hi in pin_bounds(gripper):
        lo, hi = np.minimum(lo, pin_lo), np.maximum(hi, pin_hi)
    failed, lines = False, []
    for finger in fingers:
        engraved = finger.engraving.volume_mm3
        expected = simulated - removed + added - engraved
        volume = finger.solid.Volume()
        error = abs(volume - expected) / expected
        want_lo, want_hi = (lo, hi) if finger.side == "L" else (np.array([-hi[0], lo[1], lo[2]]), np.array([-lo[0], hi[1], hi[2]]))
        box = finger.solid.BoundingBox()
        got_lo, got_hi = np.array([box.xmin, box.ymin, box.zmin]), np.array([box.xmax, box.ymax, box.zmax])
        off = float(max(np.abs(got_lo - want_lo).max(), np.abs(got_hi - want_hi).max()))
        bad = error > VOLUME_TOLERANCE or off > BOX_TOLERANCE_MM
        failed |= bad
        lines.append(
            f"{finger.side}: volume {volume:.1f} mm3 vs {expected:.1f} expected ({error:.2%}; pieces {simulated:.1f}"
            f" - mount holes and slots {removed:.1f} + pins {added:.1f} - ID {engraved:.1f}), bounding box off by {off:.3f} mm"
            + (f" (allowed: {VOLUME_TOLERANCE:.1%} and {BOX_TOLERANCE_MM:g} mm)" if bad else "")
        )
    return ExportCheck(name="matches sim", ok=not failed, blocking=True, detail="; ".join(lines))


def check_min_wall(pieces: Sequence[Piece], gripper: Gripper) -> ExportCheck:
    """MIN_WALL_MM everywhere the finger can get thin: the groove's shoulders (half the pad width minus the groove's
    half-mouth), the wall behind the groove and the lead-in, and the blade around its mount holes and slots."""
    walls = _pad_walls(pieces) + _mount_walls(gripper)
    thin = [(where, mm) for where, mm in walls if mm < MIN_WALL_MM - 1e-9]
    if thin:
        detail = "; ".join(f"{where}: {mm:.2f} mm" for where, mm in thin) + f" (needs {MIN_WALL_MM:g} mm)"
    else:
        where, mm = min(walls, key=lambda wall: wall[1])
        detail = f"thinnest wall {mm:.2f} mm ({where}); needs {MIN_WALL_MM:g} mm"
    return ExportCheck(name="min wall", ok=not thin, blocking=True, detail=detail)


def check_finger_length(gripper: Gripper, fingers: Sequence["PrintableFinger"]) -> ExportCheck:
    """The finger's length, fingertips to blade root, against the gripper maker's limit at the cell's air pressure. While
    that limit is unknown the check is a note, not a block."""
    length = max(finger.solid.BoundingBox().zlen for finger in fingers)
    limit = gripper.max_finger_length_mm
    if limit is None:
        detail = f"skipped: max finger length not confirmed for this cell (this finger is {length:.1f} mm)"
        return ExportCheck(name="finger length", ok=True, blocking=False, detail=detail)
    detail = f"{length:.1f} mm from the fingertips to the blade root; the cell allows {limit:g} mm"
    return ExportCheck(name="finger length", ok=length <= limit + 1e-6, blocking=True, detail=detail)


def check_engraved_id(fingers: Sequence["PrintableFinger"]) -> ExportCheck:
    """A note, never a block: a finger without its ID still prints and bolts on, it's just harder to match to its trials."""
    ok = all(finger.engraving.text for finger in fingers)
    detail = "; ".join(f"{finger.side}: {finger.engraving.detail}" for finger in fingers)
    return ExportCheck(name="engraved id", ok=ok, blocking=False, detail=detail)


def mount_feature_volumes(gripper: Gripper) -> tuple[float, float]:
    """The material the mount features (finger_cad.py) remove (holes, counterbores, slots) and add (pins), from their
    dimensions: holes through the blade's thickness, a counterbore from each face, stadium slots, cylindrical pins."""
    t, clearance = gripper.blade_mm[1], gripper.hole_clearance_mm
    removed = added = 0.0
    for hole in gripper.mount.holes:
        r = (hole.diameter_mm + clearance) / 2
        removed += math.pi * r * r * t
        if hole.counterbore_diameter_mm:
            bore = (hole.counterbore_diameter_mm + clearance) / 2
            if bore > r:
                removed += 2 * math.pi * (bore * bore - r * r) * min(hole.counterbore_depth_mm, t / 2)
    for feature in gripper.mount.locating:
        if feature.kind == "pin":
            added += math.pi * (feature.diameter_mm / 2) ** 2 * feature.height_mm
        else:
            w = feature.diameter_mm + clearance
            length = max(feature.length_mm, w)
            removed += (w * (length - w) + math.pi * w * w / 4) * feature.height_mm
    return removed, added


def pin_bounds(gripper: Gripper) -> list[Box]:
    """Each locating pin's bounding box on the left finger, (min xyz, max xyz): pins are the one mount feature that
    sticks out past the simulated pieces."""
    _, t, root = gripper.blade_mm
    face = 1 if gripper.mount.face == "+y" else -1
    out = []
    for pin in gripper.mount.locating:
        if pin.kind == "pin":
            r, z = pin.diameter_mm / 2, root - pin.below_root_mm
            y0, y1 = sorted((face * t / 2, face * (t / 2 + pin.height_mm)))
            out.append(((pin.x_mm - r, y0, z - r), (pin.x_mm + r, y1, z + r)))
    return out


def _pad_walls(pieces: Sequence[Piece]) -> list[tuple[str, float]]:
    """The pad's thin spots, read off the simulated pad strips (the pieces that reach the fingertips, one per straight
    stretch of the face profile). Each strip is a prism along z, so its top face gives its stretch of the face profile and
    the wall behind it, and its bottom face (cut back by any lead-in) the wall behind the lead-in."""
    strips = [p for p in pieces if min(z for *_, z in p.points) < 1e-5]
    if not strips:
        return []
    segments = sorted(s for s in (_face_segment(_face_at(p, max(z for *_, z in p.points))) for p in strips) if s)
    if not segments:
        return []
    face = min(min(x0, x1) for _, x0, _, x1, _ in segments)
    grooved = any(max(x0, x1) > face + 1e-5 for _, x0, _, x1, _ in segments)
    behind = min(back - max(x0, x1) for _, x0, _, x1, back in segments)
    walls = [("wall behind the groove" if grooved else "wall behind the pad face", behind)]
    bottom = [w for w in (_wall_behind(_face_at(p, 0.0)) for p in strips) if w is not None]
    if bottom and min(bottom) < behind - 1e-5:
        walls.append(("wall behind the lead-in", min(bottom)))
    if grooved:
        half = (segments[-1][2] - segments[0][0]) / 2
        for end, (y0, x0, y1, x1, _) in (("-y", segments[0]), ("+y", segments[-1])):
            shoulder = y1 - y0 if abs(x0 - face) < 1e-5 and abs(x1 - face) < 1e-5 else 0.0
            where = f"groove shoulder on the {end} side (half the pad width {half:.2f} minus the groove's half-mouth {half - shoulder:.2f})"
            walls.append((where, shoulder))
    return walls


def _face_at(piece: Piece, z: float) -> list[tuple[float, float]]:
    """The (x, y) corners of a strip's horizontal face at height z."""
    return [(x, y) for x, y, pz in piece.points if abs(pz - z) < 1e-5]


def _face_segment(corners: list[tuple[float, float]]) -> tuple[float, float, float, float, float] | None:
    """A strip's top face -> its stretch of the pad face, (y0, x0, y1, x1), and the x of its back."""
    if len(corners) < 3:
        return None
    back = max(x for x, _ in corners)
    inner = sorted((y, x) for x, y in corners if x < back - 1e-5)
    if len(inner) != 2:
        return None
    (y0, x0), (y1, x1) = inner
    return y0, x0, y1, x1, back


def _wall_behind(corners: list[tuple[float, float]]) -> float | None:
    if len(corners) < 3:
        return None
    back = max(x for x, _ in corners)
    inner = [x for x, _ in corners if x < back - 1e-5]
    return back - max(inner) if inner else None


def _mount_walls(gripper: Gripper) -> list[tuple[str, float]]:
    """The blade's material around its mount features: to its edges and root, between counterbores, behind slots, and
    between neighbouring holes. Holes are measured at their widest (the counterbore), with the print clearance."""
    width, t, root = gripper.blade_mm
    clearance = gripper.hole_clearance_mm
    walls, circles = [], []
    for i, hole in enumerate(gripper.mount.holes, 1):
        r = (max(hole.diameter_mm, hole.counterbore_diameter_mm or 0.0) + clearance) / 2
        name = f"mount hole {i}"
        walls += [
            (f"{name} to the blade's inner face", hole.x_mm - r),
            (f"{name} to the blade's outer face", width - hole.x_mm - r),
            (f"{name} to the blade root", hole.below_root_mm - r),
        ]
        if hole.counterbore_diameter_mm:
            depth = hole.counterbore_depth_mm
            walls.append((f"between {name}'s counterbores (blade {t:g} minus 2 x {depth:g})", t - 2 * depth))
        circles.append((name, hole.x_mm, root - hole.below_root_mm, r))
    for i, slot in enumerate((f for f in gripper.mount.locating if f.kind == "slot"), 1):
        half = (slot.diameter_mm + clearance) / 2
        name = f"locating slot {i}"
        walls += [
            (f"behind {name} (blade {t:g} minus {slot.height_mm:g} deep)", t - slot.height_mm),
            (f"{name} to the blade's inner face", slot.x_mm - half),
            (f"{name} to the blade's outer face", width - slot.x_mm - half),
        ]
    for (a, ax, az, ar), (b, bx, bz, br) in combinations(circles, 2):
        walls.append((f"between {a} and {b}", math.hypot(ax - bx, az - bz) - ar - br))
    return walls


def _volume(piece: Piece) -> float:
    """A closed, outward-wound piece's volume, from its triangles (the divergence theorem)."""
    p, t = np.asarray(piece.points, float), np.asarray(piece.triangles)
    return float(np.einsum("ij,ij->i", p[t[:, 0]], np.cross(p[t[:, 1]], p[t[:, 2]])).sum() / 6)
