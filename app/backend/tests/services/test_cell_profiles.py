import pytest

from api.models.cell_profile import DEFAULT_PROFILE, DEFAULT_PROFILE_NAME, CellProfile
from api.services import cell_profiles
from api.services.cell_profiles import CellProfileConflictError, CellProfileError, CellProfileNotFoundError

BENCH = CellProfile(stroke_per_jaw_mm=8)


def test_the_default_profile_is_seeded_once(db):
    cell_profiles.ensure_default_profile(db)
    cell_profiles.ensure_default_profile(db)

    [seeded] = cell_profiles.list_profiles(db)
    assert (seeded.name, seeded.version, seeded.profile) == (DEFAULT_PROFILE_NAME, 1, DEFAULT_PROFILE)
    assert cell_profiles.get_profile(db, seeded.id) == seeded


def test_create_saves_version_1(db):
    saved = cell_profiles.create_profile(db, "  Lab   bench ", BENCH)

    assert (saved.name, saved.version, saved.profile) == ("Lab bench", 1, BENCH)
    assert saved.created > 0
    assert cell_profiles.get_profile(db, saved.id) == saved


def test_names_are_unique_ignoring_case(db, profile_id):
    with pytest.raises(CellProfileConflictError, match="already exists"):
        cell_profiles.create_profile(db, DEFAULT_PROFILE_NAME.upper(), BENCH)

    with pytest.raises(CellProfileError, match="needs a name"):
        cell_profiles.create_profile(db, "   ", BENCH)


def test_update_adds_the_next_version_and_leaves_the_edited_one(db, profile_id):
    original = cell_profiles.get_profile(db, profile_id)

    second = cell_profiles.update_profile(db, profile_id, BENCH)
    third = cell_profiles.update_profile(db, profile_id, CellProfile(grip_force_n=120))  # edited from version 1 again

    assert (second.name, second.version, third.version) == (DEFAULT_PROFILE_NAME, 2, 3)
    assert len({profile_id, second.id, third.id}) == 3
    assert cell_profiles.get_profile(db, profile_id) == original
    assert third.profile.grip_force_n == 120


def test_list_profiles_shows_the_latest_version_of_each_name_by_name(db, profile_id):
    bench = cell_profiles.create_profile(db, "Lab bench", BENCH)
    newest = cell_profiles.update_profile(db, profile_id, CellProfile(grip_force_n=120))
    anvil = cell_profiles.create_profile(db, "anvil cell", CellProfile())

    assert [p.id for p in cell_profiles.list_profiles(db)] == [anvil.id, bench.id, newest.id]


def test_list_versions_by_any_versions_id_or_by_name(db, profile_id):
    newest = cell_profiles.update_profile(db, profile_id, BENCH)
    cell_profiles.create_profile(db, "Lab bench", BENCH)

    by_old_id = cell_profiles.list_versions(db, profile_id)

    assert [(v.id, v.version) for v in by_old_id] == [(profile_id, 1), (newest.id, 2)]
    assert cell_profiles.list_versions(db, newest.id) == by_old_id
    assert cell_profiles.list_versions(db, "  uwm  CSI   cell ") == by_old_id  # names match as create_profile stores them


@pytest.mark.parametrize(
    "call",
    [
        lambda db: cell_profiles.get_profile(db, 999),
        lambda db: cell_profiles.update_profile(db, 999, BENCH),
        lambda db: cell_profiles.list_versions(db, 999),
        lambda db: cell_profiles.list_versions(db, "no such cell"),
    ],
    ids=["get", "update", "versions by id", "versions by name"],
)
def test_an_unknown_profile_is_not_found(db, profile_id, call):
    with pytest.raises(CellProfileNotFoundError):
        call(db)
