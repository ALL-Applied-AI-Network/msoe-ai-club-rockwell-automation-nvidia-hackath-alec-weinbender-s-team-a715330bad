import dataclasses

import cadquery as cq
import pytest

from api.models.cell_profile import PHOTO_MOUNT, SMC_FLAT_JAW_MOUNT, FingerMount, Gripper, LocatingFeature, MountHole
from api.models.design import Design
from api.models.export_check import MIN_WALL_MM, check_matches_sim, check_solid, mount_feature_volumes, run_checks
from api.models.finger import build_finger, finger_solids
from api.models.finger_cad import printable_pair
from api.models.part import Part

CAP = Part()
VPAD = {"pad_width_mm": 20, "groove_angle_deg": 90, "groove_depth_mm": 3, "slack_mm": 3, "tip_height_mm": 4, "lead_in_mm": 1}
NAMES = ["solid", "matches sim", "min wall", "finger length", "engraved id"]


def checks_for(part: Part, design: Design, gripper: Gripper | None = None, fingers=None) -> dict:
    gripper = gripper or Gripper()
    fingers = fingers or printable_pair(part, design, gripper, finger_id="EXP-0042-D1")
    return {check.name: check for check in run_checks(part, design, gripper, fingers)}


@pytest.fixture(scope="module")
def vpad():
    """The V-pad's fingers for the default gripper. The length limit doesn't change the geometry, so tests of it share these."""
    return printable_pair(CAP, Design(params=VPAD), Gripper(), finger_id="EXP-0042-D1")


@pytest.mark.parametrize(
    ("part", "design"),
    [(CAP, Design(params=VPAD)), (CAP, Design(kind="imprint")), (Part(shape="box"), Design(kind="imprint"))],
    ids=["v-pad", "imprint cap", "imprint cube"],
)
def test_a_normal_design_and_the_imprint_baseline_pass_every_blocking_check(part, design):
    checks = checks_for(part, design)

    assert list(checks) == NAMES
    assert [name for name, check in checks.items() if check.blocking and not check.ok] == []
    assert "0.00%" in checks["matches sim"].detail


def test_the_min_wall_check_flags_a_groove_that_leaves_thin_shoulders():
    # A 9.5 mm deep 90 degree groove in a 20 mm pad: its mouth is 19 mm wide, leaving 0.5 mm shoulders.
    check = checks_for(CAP, Design(params={**VPAD, "groove_depth_mm": 9.5}))["min wall"]

    assert not check.ok and check.blocking
    assert "groove shoulder" in check.detail
    assert "half the pad width 10.00 minus the groove's half-mouth 9.50): 0.50 mm" in check.detail
    assert f"needs {MIN_WALL_MM:g} mm" in check.detail


def test_a_groove_that_leaves_wide_enough_shoulders_passes():
    check = checks_for(CAP, Design(params={**VPAD, "groove_depth_mm": 8.5}))["min wall"]  # 1.5 mm shoulders

    assert check.ok, check.detail


def test_the_min_wall_check_flags_counterbores_that_nearly_meet():
    mount = FingerMount(face="-y", holes=[MountHole(below_root_mm=10, x_mm=6, counterbore_depth_mm=2.6)])
    check = checks_for(CAP, Design(params=VPAD), Gripper(mount=mount))["min wall"]

    assert not check.ok
    assert "between mount hole 1's counterbores (blade 6 minus 2 x 2.6): 0.80 mm" in check.detail


def test_the_smc_jaw_mount_passes_and_its_walls_are_checked_around_holes_along_x():
    checks = checks_for(CAP, Design(params=VPAD), Gripper(mount=SMC_FLAT_JAW_MOUNT))

    assert checks["matches sim"].ok and "0.00%" in checks["matches sim"].detail
    assert checks["min wall"].ok, checks["min wall"].detail

    deep = SMC_FLAT_JAW_MOUNT.model_copy(
        update={"holes": [MountHole(below_root_mm=4, diameter_mm=2.5, depth_mm=7, counterbore_diameter_mm=None)]}
    )
    check = checks_for(CAP, Design(params=VPAD), Gripper(mount=deep))["min wall"]
    assert not check.ok
    assert "mount hole 1's floor to the blade's inner face (7.45 minus 7 deep): 0.45 mm" in check.detail


def test_matches_sim_counts_a_through_hole_and_its_counterbore_on_the_smc_mount():
    through = SMC_FLAT_JAW_MOUNT.model_copy(update={"holes": [MountHole(below_root_mm=6, diameter_mm=2.5, counterbore_depth_mm=1.5)]})
    checks = checks_for(CAP, Design(params=VPAD), Gripper(mount=through))

    assert checks["matches sim"].ok, checks["matches sim"].detail


def test_the_finger_length_check_blocks_when_the_cell_allows_less(vpad):
    check = checks_for(CAP, Design(params=VPAD), Gripper(max_finger_length_mm=60), vpad)["finger length"]

    assert not check.ok and check.blocking
    assert check.detail == "76.0 mm from the fingertips to the blade root; the cell allows 60 mm"


def test_the_finger_length_check_is_a_note_while_the_limit_is_unconfirmed(vpad):
    check = checks_for(CAP, Design(params=VPAD), Gripper(), vpad)["finger length"]

    assert check.ok and not check.blocking
    assert check.detail.startswith("skipped: max finger length not confirmed for this cell")
    assert checks_for(CAP, Design(params=VPAD), Gripper(max_finger_length_mm=80), vpad)["finger length"].ok


def test_matches_sim_allows_for_locating_pins_and_slots():
    mount = FingerMount(
        face="-y",
        holes=PHOTO_MOUNT.holes,
        locating=[
            LocatingFeature(kind="pin", below_root_mm=4, x_mm=3, diameter_mm=2, height_mm=8),  # stands out past the 20 mm pad
            LocatingFeature(kind="slot", below_root_mm=4, x_mm=9, diameter_mm=2, length_mm=5, height_mm=1),
        ],
    )
    checks = checks_for(CAP, Design(params=VPAD), Gripper(mount=mount))

    assert checks["matches sim"].ok, checks["matches sim"].detail
    assert checks["min wall"].ok, checks["min wall"].detail


def test_matches_sim_catches_a_solid_that_differs_from_the_simulated_pieces(vpad):
    """A finger missing its mount holes (as if the cut had silently failed) is caught by its volume, with the numbers."""
    gripper, design = Gripper(), Design(params=VPAD)
    left, right = vpad
    solids = finger_solids(CAP, design, gripper)
    no_holes = dataclasses.replace(left, solid=solids[0].fuse(*solids[1:]).clean())
    removed, _ = mount_feature_volumes(gripper)

    check = check_matches_sim(build_finger(CAP, design, gripper).pieces, gripper, [no_holes, right])

    assert not check.ok and check.blocking
    assert f"mount cuts {removed:.1f}" in check.detail and "(allowed: 0.5% and 0.05 mm)" in check.detail


def test_the_solid_check_needs_exactly_one_closed_solid_per_side(vpad):
    left, right = vpad
    two = cq.Compound.makeCompound([cq.Solid.makeBox(1, 1, 1), cq.Solid.makeBox(1, 1, 1, pnt=cq.Vector(5, 0, 0))])

    assert check_solid([left, right]).ok
    check = check_solid([left, dataclasses.replace(right, solid=two)])
    assert not check.ok and check.detail == "R: 2 solids, needs exactly 1"


def test_a_missing_engraving_is_a_note_not_a_block():
    tall = Part(shape="box", height_mm=40)
    check = checks_for(tall, Design(params={"pad_width_mm": 8, "slack_mm": 3, "tip_height_mm": 4}))["engraved id"]

    assert not check.ok and not check.blocking
    assert "skipped: no room for legible text" in check.detail
