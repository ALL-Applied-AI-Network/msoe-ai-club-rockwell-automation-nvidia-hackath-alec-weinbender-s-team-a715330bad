import io

import pytest
import trimesh

from api.config import CAD_DIR
from api.services import parts


@pytest.fixture
def upload(client, shapes, step_file):
    """upload(name) -> the JSON of that test part, uploaded as a STEP through the API."""

    def post(name: str = "cube") -> dict:
        response = client.post("/api/parts", files={"part_file": (f"{name}.step", step_file(shapes[name], f"{name}.step"))})
        assert response.status_code == 201, response.text
        return response.json()

    return post


def test_an_upload_returns_the_record_with_its_bounding_box(upload):
    part = upload("vial_cap")

    assert part["extent_mm"] == pytest.approx([31.75, 31.75, 15.7], abs=0.05) and part["extent_mm"] == part["measured"]["extent_mm"]
    assert part["n_pieces"] == len(part["measured"]["pieces"]) > 1
    assert (part["name"], part["source"], part["units"], part["pose"]) == ("vial_cap.step", "step", "mm", None)
    assert [part[k] for k in ("material", "density", "computed_mass_g", "mass_source", "confirmed_mass_g")] == [None] * 5
    assert part["friction_vs_pad"] == [0.6, 0.5]


def test_lab_parts_are_flagged_and_uploads_are_not(client, db, config, cad, upload):
    parts.ensure_lab_parts(db, config, cad, CAD_DIR)
    uploaded = upload("cube")

    listed = {p["id"]: p for p in client.get("/api/parts").json()}
    assert listed["lab-vial-cap"]["lab"] and listed["lab-vial-cap"]["name"] == "Vial cap, Ø32 mm"
    assert not listed[uploaded["id"]]["lab"] and not uploaded["lab"]


def test_an_stl_needs_units_and_inches_become_mm(client, shapes, stl_file):
    content = stl_file(shapes["cube"], scale=1 / 25.4)

    missing = client.post("/api/parts", files={"part_file": ("cube.stl", content)})
    inches = client.post("/api/parts", files={"part_file": ("cube.stl", content)}, data={"units": "in"})

    assert (missing.status_code, missing.json()["detail"]) == (422, "units required for STL: mm or in")
    assert inches.status_code == 201 and inches.json()["units"] == "in"
    assert inches.json()["extent_mm"] == pytest.approx([10, 10, 10], abs=1e-3)


def test_a_solidworks_part_is_415_with_the_export_hint(client):
    response = client.post("/api/parts", files={"part_file": ("bracket.SLDPRT", b"\x00" * 64)})

    assert response.status_code == 415
    assert response.json()["detail"].endswith("In SolidWorks: File > Save As > STEP.")


def test_unreadable_uploads_are_422(client):
    junk = client.post("/api/parts", files={"part_file": ("junk.step", b"not a step file")})
    no_file = client.post("/api/parts", data={"units": "mm"})
    bad_units = client.post("/api/parts", files={"part_file": ("cube.stl", b"solid")}, data={"units": "cm"})

    assert [r.status_code for r in (junk, no_file, bad_units)] == [422, 422, 422]
    assert "not a readable STEP file" in junk.json()["detail"]


def test_the_list_is_newest_first_without_the_pieces(client, upload):
    first, second = upload("cube"), upload("l_bracket")

    listed = client.get("/api/parts").json()
    detail = client.get(f"/api/parts/{second['id']}").json()

    assert [p["id"] for p in listed] == [second["id"], first["id"]]
    assert [p["measured"]["pieces"] for p in listed] == [[], []] and listed[0]["n_pieces"] == second["n_pieces"] > 1
    assert detail == second
    assert client.get("/api/parts/nope").status_code == 404


def test_patch_changes_only_what_is_sent_and_mass_null_means_computed(client, upload):
    url = f"/api/parts/{upload('cube')['id']}"

    aluminium = client.patch(url, json={"material": "aluminium", "fragile": True}).json()
    weighed = client.patch(url, json={"mass_g": 3.1, "mass_unit": "oz"}).json()
    computed = client.patch(url, json={"mass_g": None}).json()

    assert (aluminium["density"], aluminium["computed_mass_g"], aluminium["mass_source"]) == (2.7, pytest.approx(2.7), "computed")
    assert aluminium["friction_vs_pad"] == [0.45, 0.35]
    assert (weighed["material"], weighed["fragile"], weighed["mass_unit"]) == ("aluminium", True, "oz")
    assert (weighed["mass_source"], weighed["confirmed_mass_g"], weighed["computed_mass_g"]) == ("measured", 3.1, pytest.approx(2.7))
    assert (computed["mass_g"], computed["mass_source"], computed["confirmed_mass_g"]) == (None, "computed", pytest.approx(2.7))
    assert client.get(url).json() == computed


@pytest.mark.parametrize(
    "body",
    [{"material": "other"}, {"surface": None}, {"fragile": None}, {"colour": "red"}, {"mass_g": -2}, {"pose": "sideways"}, {"pose": 7}],
)
def test_patch_refuses_what_it_cant_apply(client, upload, body):
    response = client.patch(f"/api/parts/{upload('cube')['id']}", json=body)

    assert response.status_code == 422, response.text


def test_patch_on_an_unknown_part_is_404(client):
    assert client.patch("/api/parts/nope", json={"fragile": True}).status_code == 404


def test_friction_follows_the_cell_profile_asked_about(client, upload, profile_id):
    part = upload("cube")

    assert client.get(f"/api/parts/{part['id']}?cell_profile_id={profile_id}").json()["friction_vs_pad"] == [0.6, 0.5]
    assert client.get(f"/api/parts/{part['id']}?cell_profile_id=999").status_code == 404


def test_poses_are_indexed_and_the_chosen_one_is_marked(client, upload):
    url = f"/api/parts/{upload('glass_tube')['id']}"

    before = client.get(f"{url}/poses").json()
    chosen = client.patch(url, json={"pose": 1}).json()
    after = client.get(f"{url}/poses").json()
    authored = client.patch(url, json={"pose": "as_authored"}).json()

    assert [(p["index"], p["label"], p["chosen"]) for p in before] == [
        (0, "lying on its side", False),
        (1, "standing on an end", False),
        (2, "as in the CAD file", False),
    ]
    assert chosen["pose"]["label"] == "standing on an end" and chosen["pose"]["extent_mm"] == pytest.approx([17, 17, 140], abs=0.05)
    assert [p["chosen"] for p in after] == [False, True, False]
    assert authored["pose"]["source"] == "as_authored"


def test_the_mesh_is_a_binary_stl_in_the_table_frame(client, upload):
    url = f"/api/parts/{upload('glass_tube')['id']}"

    standing = client.get(f"{url}/mesh?pose=1")
    default = client.get(f"{url}/mesh")

    assert standing.status_code == 200 and standing.headers["content-type"] == "model/stl"
    mesh = trimesh.load(io.BytesIO(standing.content), file_type="stl")
    assert mesh.extents == pytest.approx((17, 17, 140), abs=0.05) and mesh.bounds[0][2] == pytest.approx(0)
    assert trimesh.load(io.BytesIO(default.content), file_type="stl").extents == pytest.approx((140, 17, 17), abs=0.05)
    assert client.get(f"{url}/mesh?pose=sideways").status_code == 422
    assert client.get(f"{url}/mesh?pose=9").status_code == 422
    assert client.get("/api/parts/nope/mesh").status_code == 404


def test_grasp_proposals_need_a_pose_and_a_known_profile(client, upload, profile_id):
    url = f"/api/parts/{upload('cube')['id']}"

    no_pose = client.post(f"{url}/grasps", json={"cell_profile_id": profile_id})
    client.patch(url, json={"pose": 0})
    proposals = client.post(f"{url}/grasps", json={"cell_profile_id": profile_id})

    assert (no_pose.status_code, no_pose.json()["detail"]) == (409, "choose a resting pose first")
    assert proposals.status_code == 200
    assert [c["angle_deg"] for c in proposals.json()["candidates"]] == [0, 90] and proposals.json()["nothing_fits"] is None
    assert client.post(f"{url}/grasps", json={"cell_profile_id": 999}).status_code == 404
    assert client.post("/api/parts/nope/grasps", json={"cell_profile_id": profile_id}).status_code == 404


def test_a_too_wide_part_says_what_would_fit(client, upload, profile_id):
    url = f"/api/parts/{upload('wide_plate')['id']}"
    client.patch(url, json={"pose": 0})  # lying flat

    nothing = client.post(f"{url}/grasps", json={"cell_profile_id": profile_id}).json()["nothing_fits"]

    assert nothing["reason"] == "narrowest width 120.0 mm (at 0°); these fingers reach around at most 83.0 mm"
    assert any(s.startswith('another resting pose: "on its side"') for s in nothing["suggestions"])


def test_a_manual_grasp_is_checked_and_comes_with_its_choice(client, upload, profile_id):
    url = f"/api/parts/{upload('cube')['id']}"
    client.patch(url, json={"pose": 0})
    pick = {"point": [0, -5, 4], "normal": [0, -1, 0]}

    by_angle = client.post(f"{url}/grasps/check", json={"cell_profile_id": profile_id, "angle_deg": 270}).json()
    by_pick = client.post(f"{url}/grasps/check", json={"cell_profile_id": profile_id, "picks": [pick], "grip_height_mm": 2}).json()

    assert (by_angle["angle_deg"], by_angle["verdict"]) == (90, "ok")
    assert by_angle["choice"] == {"angle_deg": 90, "centre_mm": [0, 0], "source": "manual", "grip_height_mm": None, "picks": []}
    assert by_pick["verdict"] == "ok" and by_pick["choice"]["picks"] == [pick] and by_pick["choice"]["grip_height_mm"] == 2


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"picks": [{"point": [5, 0, 4], "normal": [1, 0, 0]}] * 2},
        {"picks": [{"point": [0, 0, 10], "normal": [0, 0, 1]}]},
        {"picks": [{"point": [5, 0, 4], "normal": [1, 0, 0]}] * 3},
        {"angle_deg": 0, "grip_height_mm": 50},
    ],
)
def test_a_manual_grasp_that_sets_no_direction_is_422(client, upload, profile_id, body):
    url = f"/api/parts/{upload('cube')['id']}"
    client.patch(url, json={"pose": 0})

    response = client.post(f"{url}/grasps/check", json={"cell_profile_id": profile_id, **body})

    assert response.status_code == 422, response.text
