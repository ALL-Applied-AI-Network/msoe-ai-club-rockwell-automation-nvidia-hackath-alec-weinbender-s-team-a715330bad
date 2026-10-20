from typing import get_args

import pytest
from pydantic import ValidationError

from api.config import SimConfig
from api.models.error_model import PRESETS
from api.models.family import FAMILIES
from api.models.material import MATERIALS, SURFACE_FACTORS
from api.models.part_record import GRAMS_PER
from api.models.task import TASK_LABELS, Task, TaskKind


@pytest.fixture
def meta(client) -> dict:
    response = client.get("/api/meta")
    assert response.status_code == 200
    return response.json()


def test_meta_lists_materials_with_density_and_pad_friction(meta):
    materials = {m["name"]: m for m in meta["materials"]}

    assert list(materials) == list(MATERIALS)
    assert materials["glass"] == {"name": "glass", "label": "Glass", "density_g_cm3": 2.5, "friction": [0.4, 0.3]}
    assert (materials["other"]["density_g_cm3"], materials["other"]["friction"]) == (None, None)


def test_meta_lists_surfaces_and_their_friction_factors(meta):
    assert {s["name"]: s["friction_factor"] for s in meta["surfaces"]} == SURFACE_FACTORS
    assert [s["label"] for s in meta["surfaces"]] == ["Smooth", "Oily", "Textured"]


def test_meta_describes_each_family_and_the_built_ones_parameters(meta):
    families = {f["name"]: f for f in meta["families"]}

    assert list(families) == list(FAMILIES)
    vpad = families["vpad"]
    assert (vpad["status"], vpad["fields"]) == ("built", FAMILIES["vpad"].fields)
    fields = vpad["params_schema"]["properties"]
    assert all(fields[name]["description"] for name in vpad["fields"])
    assert fields["groove_angle_deg"]["applies_to"] == "upright cylinders"
    assert (fields["groove_angle_deg"]["minimum"], fields["groove_angle_deg"]["maximum"]) == (60, 180)
    cradle = families["cradle"]
    assert (cradle["status"], cradle["only_for"], cradle["fields"], cradle["params_schema"]) == ("planned", "lying cylinders", [], None)


def test_meta_lists_the_error_presets(meta):
    presets = {p["name"]: p for p in meta["error_presets"]}

    assert list(presets) == list(PRESETS)
    assert presets["twin"] == {
        "name": "twin",
        "label": "Twin perception",
        "sigma_mm": 0.19,
        "sigma_deg": 0.5,
        "placeholder": False,
        "note": PRESETS["twin"].note,
    }
    assert all(p["placeholder"] for name, p in presets.items() if name != "twin")


def test_meta_task_kinds_list_exactly_the_tolerances_a_task_needs(meta):
    values = {"offset_tolerance_mm": 2.0, "tilt_tolerance_deg": 5.0}
    kinds = {k["name"]: k for k in meta["task_kinds"]}

    assert list(kinds) == list(get_args(TaskKind))
    for name, kind in kinds.items():
        assert kind["label"] == TASK_LABELS[name]
        Task(kind=name, **{field: values[field] for field in kind["tolerances"]})
        for missing in kind["tolerances"]:
            with pytest.raises(ValidationError, match=missing):
                Task(kind=name, **{field: values[field] for field in kind["tolerances"] if field != missing})


def test_meta_lists_transport_speeds_and_mass_units(meta):
    assert [(t["name"], t["move_s"]) for t in meta["transports"]] == [("slow", 1.2), ("normal", 0.6), ("fast", 0.3)]
    assert all((t["distance_mm"], t["settle_s"]) == (120, 0.5) for t in meta["transports"])
    assert {u["name"]: u["grams"] for u in meta["mass_units"]} == GRAMS_PER


def test_meta_reports_the_mock_backends_and_the_mock_badge(meta):
    assert meta["sim"] == {"backend": "mock", "badge": "mock", "url": None}
    assert meta["llm"] == "mock"
    assert meta["cpus"] is None or meta["cpus"] >= 1


def test_meta_badges_the_sim_server_as_isaac(client, config):
    config.sim = SimConfig(backend="http", url="http://gpu:9000")

    assert client.get("/api/meta").json()["sim"] == {"backend": "http", "badge": "isaac", "url": "http://gpu:9000"}


def test_meta_says_when_the_app_runs_on_demo_data(client, config):
    assert client.get("/api/meta").json()["demo_data"] is False
    config.demo_data = True
    assert client.get("/api/meta").json()["demo_data"] is True
