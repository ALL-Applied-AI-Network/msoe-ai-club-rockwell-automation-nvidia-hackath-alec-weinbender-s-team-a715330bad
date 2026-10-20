import pytest

from api.models.part import Part
from api.models.part_cad import PartCad
from api.models.part_record import PartRecord

MEASURED = PartCad(
    filename="cube.step",
    source="step",
    extent_mm=(10, 10, 10),
    volume_mm3=1000,
    centre_of_mass_mm=(0, 0, 5),
    fit="box",
    suggested=Part(shape="box"),
    pieces=[],
)


def record(**fields) -> PartRecord:
    return PartRecord(id="p", created=0, name="cube.step", file_path="cube.step", source="step", units="mm", measured=MEASURED, **fields)


def test_mass_is_computed_from_the_material_until_one_is_measured():
    computed = record(material="pla")
    measured = record(material="pla", mass_g=2.0)

    assert (computed.density, computed.computed_mass_g) == (1.24, pytest.approx(1.24))
    assert (computed.mass_source, computed.confirmed_mass_g) == ("computed", pytest.approx(1.24))
    assert (measured.mass_source, measured.confirmed_mass_g, measured.computed_mass_g) == ("measured", 2.0, pytest.approx(1.24))


def test_an_entered_density_overrides_the_materials():
    assert record(material="glass", density_g_cm3=3.0).computed_mass_g == pytest.approx(3.0)
    assert record(material="other", density_g_cm3=0.9).confirmed_mass_g == pytest.approx(0.9)


def test_without_a_density_there_is_no_mass():
    for unknown in (record(), record(material="other")):
        assert (unknown.density, unknown.computed_mass_g, unknown.mass_source, unknown.confirmed_mass_g) == (None, None, None, None)


def test_friction_is_the_materials_pair_scaled_by_the_surface():
    assert record(material="glass").friction((0.6, 0.5)) == (0.4, 0.3)
    assert record(material="glass", surface="oily").friction((0.6, 0.5)) == (0.2, 0.15)
    assert record(material="other", surface="textured").friction((0.6, 0.5)) == (0.72, 0.6)  # the pad's own
    assert record().friction((0.7, 0.6)) == (0.7, 0.6)
