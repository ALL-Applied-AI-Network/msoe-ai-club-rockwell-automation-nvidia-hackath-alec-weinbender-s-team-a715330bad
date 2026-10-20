import pytest

from api.models.cell_profile import DEFAULT_PROFILE, PHOTO_MOUNT, SMC_FLAT_JAW_MOUNT, TWIN_CELL, CellProfile, CellSimSettings


def test_the_default_profile_is_the_twins_cell_with_its_placeholders_marked():
    assert DEFAULT_PROFILE.twin_mismatches() == []
    assert {"grip_force_n", "finger_mount", "max_finger_length_mm"} <= set(DEFAULT_PROFILE.to_confirm)
    assert TWIN_CELL.to_confirm == []


def test_the_default_mount_is_smcs_jaw_from_its_step():
    mount = DEFAULT_PROFILE.finger_mount

    assert mount == SMC_FLAT_JAW_MOUNT and mount.face == "+x"
    assert (mount.face_x_mm, mount.jaw_length_mm, mount.face_size_mm) == (7.45, 15.0, (8.0, 15.0))
    assert [hole.below_root_mm for hole in mount.holes] == [4.0, 11.0], "7 mm apart, as the STEP's jaw holes"
    assert mount.describe() == (
        "screws through the jaw beside the blade's root, into holes 4 and 11 mm below the root; the root is cut back to "
        "7.45 mm from the inner face for its top 15.5 mm"
    )
    assert PHOTO_MOUNT.describe() == "screws through the blade's thickness, 10 and 23 mm below the root, its -y face against the jaw"


def test_a_profile_whose_blade_is_narrower_than_the_jaws_face_needs_another_mount():
    with pytest.raises(ValueError, match="outside the 6 mm blade"):
        CellProfile(stock_finger_mm=(6, 12, 76))

    assert CellProfile(stock_finger_mm=(6, 12, 76), finger_mount=PHOTO_MOUNT).gripper.blade_mm == (6, 12, 76)


def test_twin_mismatches_name_each_setting_the_sim_models_differently():
    profile = CellProfile(gripper_model="SCHUNK MPG-plus 25", stroke_per_jaw_mm=8, stock_finger_mm=(12, 6, 80), lift_m=0.2)

    assert profile.twin_mismatches() == [
        "the sim models a SMC MHZL2-16D2, not a SCHUNK MPG-plus 25",
        "stroke_per_jaw_mm: this profile has 8 mm, the sim's twin 6 mm",
        "stock_finger_mm: this profile has 12 × 6 × 80 mm, the sim's twin 12 × 6 × 76 mm",
        "lift_m: this profile has 0.2 m, the sim's twin 0.13 m",
    ]


def test_settings_that_only_shape_the_printed_finger_are_not_mismatches():
    profile = CellProfile(free_space_mm=(40, 25), hole_clearance_mm=0.4, grip_force_n=150, pad_friction=(0.7, 0.6), max_finger_length_mm=90)

    assert profile.twin_mismatches() == []


def test_gripper_carries_what_finger_geometry_and_cad_take_from_the_profile():
    profile = CellProfile(
        stroke_per_jaw_mm=8, stock_finger_mm=(14, 5, 70), free_space_mm=(40, 25), hole_clearance_mm=0.4, max_finger_length_mm=90
    )

    gripper = profile.gripper

    assert (gripper.stroke_mm, gripper.blade_mm, gripper.free_space_mm) == (8, (14, 5, 70), (40, 25))
    assert (gripper.hole_clearance_mm, gripper.max_finger_length_mm, gripper.mount) == (0.4, 90, profile.finger_mount)
    assert (gripper.tcp_mm, gripper.stock_tip_gap_mm, gripper.pad_friction) == (293, 16, (0.6, 0.5))


def test_sim_settings_compare_only_what_the_server_reports():
    settings = CellSimSettings()

    assert settings.differences({}) == []
    assert settings.differences({"envs": 64, "physics_dt": 1 / 60, "device": "cuda:0", "friction_combine": "average"}) == []
    assert settings.differences({"envs": 128, "physics_dt": 1 / 120, "solver_position_iterations": True}) == [
        "physics_dt_s: this profile asks for 0.0166667, the sim server runs 0.00833333",
        "envs: this profile asks for 64, the sim server runs 128",
    ]
