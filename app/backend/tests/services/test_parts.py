import io
import re
from pathlib import Path

import pytest
import trimesh

from api.models.cell_profile import DEFAULT_PROFILE
from api.models.grasp import GraspPick
from api.services import cell_profiles, parts


@pytest.fixture
def upload(db, config, cad, shapes, step_file):
    """upload(name) -> the PartRecord of that test part, uploaded as a STEP."""

    def create(name: str = "cube"):
        return parts.create_part(db, config, cad, f"{name}.step", step_file(shapes[name], f"{name}.step"), None)

    return create


def load_stl(data: bytes) -> trimesh.Trimesh:
    return trimesh.load(io.BytesIO(data), file_type="stl")


def test_a_step_upload_is_measured_and_stored_next_to_its_mesh(db, config, upload):
    record = upload("vial_cap")

    folder = config.uploads_dir / f"part_{record.id}"
    assert Path(record.file_path) == folder / "vial_cap.step" and Path(record.file_path).read_bytes().startswith(b"ISO-10303-21")
    assert (record.name, record.source, record.units, record.measured.fit) == ("vial_cap.step", "step", "mm", "standing cylinder")
    assert (record.material, record.pose, record.mass_source) == (None, None, None)
    mesh = parts.load_mesh(record)
    assert (folder / parts.MESH_FILE).exists() and mesh.vertices.shape[1] == 3 and mesh.triangles.shape[1] == 3
    assert mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0) == pytest.approx(record.measured.extent_mm)
    assert parts.get_part(db, record.id) == record


def test_a_step_files_material_is_preselected(db, config, cad, shapes, step_file):
    content = step_file(shapes["cube"]).replace(b"PRODUCT('", b"PRODUCT('6061 aluminium ", 1)

    record = parts.create_part(db, config, cad, "block.step", content, None)

    assert record.material == "aluminium" and record.computed_mass_g == pytest.approx(2.7)


def test_an_stl_in_inches_is_stored_in_mm(db, config, cad, shapes, stl_file):
    record = parts.create_part(db, config, cad, "cube.stl", stl_file(shapes["cube"], scale=1 / 25.4), "in")

    assert (record.source, record.units) == ("stl", "in")
    assert record.measured.extent_mm == pytest.approx((10, 10, 10), abs=1e-3)
    assert record.measured.volume_mm3 == pytest.approx(1000, rel=1e-3)


def test_an_stl_needs_its_units(db, config, cad, shapes, stl_file):
    with pytest.raises(parts.PartFileError, match="units required for STL: mm or in"):
        parts.create_part(db, config, cad, "cube.stl", stl_file(shapes["cube"]), None)


def test_a_solidworks_file_is_unsupported_and_says_how_to_export(db, config, cad):
    with pytest.raises(parts.UnsupportedPartFormatError, match=re.escape("In SolidWorks: File > Save As > STEP.")):
        parts.create_part(db, config, cad, "bracket.SLDPRT", b"\x00" * 64, None)


def test_unreadable_and_oversized_files_are_refused_and_nothing_is_stored(db, config, cad, monkeypatch):
    with pytest.raises(parts.PartFileError, match="not a readable STEP file"):
        parts.create_part(db, config, cad, "junk.step", b"not a step file", None)
    monkeypatch.setattr(parts, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(parts.PartFileError, match="larger than"):
        parts.create_part(db, config, cad, "big.step", b"x" * 11, None)

    assert parts.list_parts(db) == [] and not config.uploads_dir.exists()


def test_the_stored_name_is_never_a_path(db, config, cad, shapes, step_file):
    record = parts.create_part(db, config, cad, "../../evil.step", step_file(shapes["cube"]), None)

    assert record.name == "evil.step" and Path(record.file_path).parent == config.uploads_dir / f"part_{record.id}"


def test_parts_are_listed_newest_first(db, upload):
    first, second = upload("cube"), upload("l_bracket")

    assert [p.id for p in parts.list_parts(db)] == [second.id, first.id]


def test_an_unknown_part_is_not_found(db):
    for call in (lambda: parts.get_part(db, "nope"), lambda: parts.update_part(db, "nope", {}), lambda: parts.mesh_stl(db, "nope")):
        with pytest.raises(parts.PartNotFoundError):
            call()


def test_patch_changes_only_the_fields_sent_and_mass_switches_between_computed_and_measured(db, upload):
    record = upload("cube")

    pla = parts.update_part(db, record.id, {"material": "pla"})
    weighed = parts.update_part(db, record.id, {"mass_g": 2.5, "fragile": True})
    back = parts.update_part(db, record.id, {"mass_g": None})

    assert (pla.mass_source, pla.confirmed_mass_g) == ("computed", pytest.approx(1.24))
    assert (weighed.material, weighed.fragile, weighed.mass_source, weighed.confirmed_mass_g) == ("pla", True, "measured", 2.5)
    assert (back.fragile, back.mass_source, back.confirmed_mass_g) == (True, "computed", pytest.approx(1.24))
    assert parts.get_part(db, record.id) == back


def test_other_needs_a_density_and_bad_values_are_refused(db, upload):
    record = upload("cube")

    with pytest.raises(parts.PartInputError, match='"other" needs density_g_cm3'):
        parts.update_part(db, record.id, {"material": "other"})
    with pytest.raises(parts.PartInputError, match="mass_g"):
        parts.update_part(db, record.id, {"mass_g": -1})
    with pytest.raises(parts.PartInputError, match="can't change colour"):
        parts.update_part(db, record.id, {"colour": "red"})
    other = parts.update_part(db, record.id, {"material": "other", "density_g_cm3": 2.0})

    assert other.computed_mass_g == pytest.approx(2.0)


def test_choosing_a_resting_pose_stores_the_pose_itself(db, upload):
    record = upload("glass_tube")
    poses = parts.resting_poses(db, record.id)

    standing = parts.update_part(db, record.id, {"pose": 1})
    authored = parts.update_part(db, record.id, {"pose": "as_authored"})

    assert [p.label for p in poses] == ["lying on its side", "standing on an end", "as in the CAD file"]
    assert standing.pose == poses[1]
    assert (authored.pose.source, authored.pose.extent_mm) == ("as_authored", pytest.approx((140, 17, 17), abs=0.05))
    with pytest.raises(parts.PartInputError, match='index from 0 to 2, or "as_authored"'):
        parts.update_part(db, record.id, {"pose": 3})
    assert parts.update_part(db, record.id, {"pose": None}).pose is None


def test_the_mesh_stl_is_in_the_table_frame_of_the_pose_asked_for(db, upload):
    record = upload("glass_tube")
    parts.update_part(db, record.id, {"pose": 1})  # standing on an end

    chosen, lying, authored = (load_stl(parts.mesh_stl(db, record.id, pose)) for pose in (None, 0, "as_authored"))

    assert chosen.extents == pytest.approx((17, 17, 140), abs=0.05)
    assert chosen.bounds[0][2] == pytest.approx(0) and chosen.bounds.sum(axis=0)[:2] == pytest.approx((0, 0), abs=1e-6)
    assert lying.extents == pytest.approx((140, 17, 17), abs=0.05) and authored.extents == pytest.approx((140, 17, 17), abs=0.05)
    with pytest.raises(parts.PartInputError):
        parts.mesh_stl(db, record.id, 9)


def test_grasps_need_a_chosen_pose(db, upload):
    record = upload("cube")

    with pytest.raises(parts.PoseNotChosenError, match="choose a resting pose first"):
        parts.propose_grasps(db, record.id, DEFAULT_PROFILE)
    with pytest.raises(parts.PoseNotChosenError):
        parts.check_grasp(db, record.id, DEFAULT_PROFILE, angle_deg=0)


def test_grasps_are_proposed_and_checked_on_the_chosen_pose_and_profile(db, upload, profile_id):
    record = upload("cube")
    parts.update_part(db, record.id, {"pose": 0})
    profile = cell_profiles.get_profile(db, profile_id).profile

    proposals = parts.propose_grasps(db, record.id, profile)
    checked = parts.check_grasp(db, record.id, profile, picks=[GraspPick(point=(5, 0, 4), normal=(1, 0, 0))])

    assert [c.angle_deg for c in proposals.candidates] == [0, 90]
    assert (checked.angle_deg, checked.verdict) == (0, "ok")
    with pytest.raises(parts.PartInputError, match="pick a side face"):
        parts.check_grasp(db, record.id, profile, picks=[GraspPick(point=(0, 0, 10), normal=(0, 0, 1))])


def test_the_profiles_free_space_decides_what_fits(db, upload):
    record = upload("vial_cap")
    parts.update_part(db, record.id, {"pose": 0})  # standing on an end
    cramped = DEFAULT_PROFILE.model_copy(update={"free_space_mm": (15.0, 30.0)})

    proposals = parts.propose_grasps(db, record.id, cramped)

    assert proposals.candidates == []
    assert proposals.nothing_fits.reason.endswith("these fingers reach around at most 23.0 mm")


def test_grasps_can_be_proposed_and_checked_in_any_pose(db, upload, profile_id):
    record = upload("bar")
    profile = cell_profiles.get_profile(db, profile_id).profile

    lying, standing = parts.propose_grasps(db, record.id, profile, 0), parts.propose_grasps(db, record.id, profile, 1)
    checked = parts.check_grasp(db, record.id, profile, angle_deg=0, pose=1)

    assert parts.get_part(db, record.id).pose is None  # no chosen pose needed when the pose is given
    assert [c.angle_deg for c in lying.candidates][:2] == [90, 0] and [c.angle_deg for c in standing.candidates] == [0, 90]
    assert (checked.verdict, checked.width_mm) == ("ok", pytest.approx(10))
    with pytest.raises(parts.PartInputError, match="pose must be an index"):
        parts.propose_grasps(db, record.id, profile, 7)


def test_poses_resolve_from_one_list(db, upload):
    record = upload("bar")

    lying, authored = parts.resolve_poses(record, [0, "as_authored"])

    assert (lying.label, lying.probability) == ("on its side", pytest.approx(0.8718, abs=1e-3))
    assert authored.source == "as_authored" and parts.resolve_pose(record, 1).label == "standing"


def test_many_files_are_stored_each_on_its_own(db, config, cad, shapes, step_file, stl_file):
    files = [
        ("orders/cube.step", step_file(shapes["cube"], "cube.step")),
        ("orders/readme.txt", b"not a part"),
        ("orders/broken.step", b"not a step file"),
        ("orders/bar.stl", stl_file(shapes["bar"], "bar.stl")),
    ]

    intakes = parts.create_parts(db, config, cad, files, "mm")

    assert [(i.filename, i.status) for i in intakes] == [
        ("cube.step", "needs_properties"),
        ("readme.txt", "skipped"),
        ("broken.step", "file_error"),
        ("bar.stl", "needs_properties"),
    ]
    assert intakes[2].reason and intakes[2].part is None
    assert {p.name for p in parts.list_parts(db)} == {"cube.step", "bar.stl"}
    ready = parts.update_part(db, intakes[0].part.id, {"material": "pla"})
    assert ready.intake_status == "ready"


def test_a_batch_with_too_many_cad_files_is_refused(db, config, cad, monkeypatch):
    monkeypatch.setattr(parts, "MAX_BATCH_FILES", 1)

    with pytest.raises(parts.PartFileError, match="at most 1"):
        parts.create_parts(db, config, cad, [("a.step", b""), ("b.step", b"")], None)
    assert parts.list_parts(db) == []


def test_a_part_can_be_renamed_and_numbered(db, upload):
    record = upload()

    named = parts.update_part(db, record.id, {"name": "  Vial   cap ", "part_number": " 4471-A "})
    assert (named.name, named.part_number) == ("Vial cap", "4471-A")
    assert parts.update_part(db, record.id, {"part_number": " "}).part_number is None
    with pytest.raises(parts.PartInputError, match="needs a name"):
        parts.update_part(db, record.id, {"name": "  "})
