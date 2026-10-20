import pytest

from api.models.cell_profile import DEFAULT_PROFILE_NAME

URL = "/api/cell-profiles"


def test_list_shows_the_default_profile_with_what_the_sim_models_and_the_gripper(client, profile_id):
    [profile] = client.get(URL).json()

    assert (profile["id"], profile["name"], profile["version"]) == (profile_id, DEFAULT_PROFILE_NAME, 1)
    assert profile["twin_mismatches"] == []
    assert (profile["gripper"]["stroke_mm"], profile["gripper"]["blade_mm"]) == (6.0, [12.0, 6.0, 76.0])
    assert "grip_force_n" in profile["profile"]["to_confirm"]


def test_create_returns_version_1_with_its_twin_mismatches(client, profile_id):
    response = client.post(URL, json={"name": "Lab bench", "profile": {"stroke_per_jaw_mm": 8}})

    assert response.status_code == 201
    created = response.json()
    assert (created["name"], created["version"], created["gripper"]["stroke_mm"]) == ("Lab bench", 1, 8)
    assert created["twin_mismatches"] == ["stroke_per_jaw_mm: this profile has 8 mm, the sim's twin 6 mm"]
    assert client.get(f"{URL}/{created['id']}").json() == created


def test_create_refuses_a_taken_name(client, profile_id):
    response = client.post(URL, json={"name": DEFAULT_PROFILE_NAME.lower(), "profile": {}})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [{"name": "   ", "profile": {}}, {"name": "", "profile": {}}, {"name": "x", "profile": {"stroke_per_jaw_mm": -1}}, {"name": "x"}],
    ids=["blank name", "empty name", "negative stroke", "no profile"],
)
def test_create_rejects_an_invalid_profile(client, body):
    assert client.post(URL, json=body).status_code == 422


def test_put_saves_a_new_version_and_leaves_the_edited_one(client, profile_id):
    old = client.get(f"{URL}/{profile_id}").json()
    edited = {**old, "profile": {**old["profile"], "grip_force_n": 120}}  # the UI sends back what it got, edited

    response = client.put(f"{URL}/{profile_id}", json=edited)

    assert response.status_code == 200
    new = response.json()
    assert new["id"] != profile_id
    assert (new["name"], new["version"], new["profile"]["grip_force_n"]) == (DEFAULT_PROFILE_NAME, 2, 120)
    assert client.get(f"{URL}/{profile_id}").json() == old
    assert [p["id"] for p in client.get(URL).json()] == [new["id"]]


def test_versions_lists_every_version_oldest_first(client, profile_id):
    new = client.put(f"{URL}/{profile_id}", json={"profile": {"grip_force_n": 120}}).json()

    versions = client.get(f"{URL}/{new['id']}/versions").json()

    assert [(v["id"], v["version"]) for v in versions] == [(profile_id, 1), (new["id"], 2)]
    assert all("twin_mismatches" in v and "gripper" in v for v in versions)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("get", "/999", None), ("put", "/999", {"profile": {}}), ("get", "/999/versions", None)],
    ids=["get", "put", "versions"],
)
def test_an_unknown_id_is_404(client, profile_id, method, path, body):
    response = client.request(method, f"{URL}{path}", json=body)

    assert response.status_code == 404
    assert "999" in response.json()["detail"]
