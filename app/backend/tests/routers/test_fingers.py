CAP = {"shape": "cylinder", "diameter_mm": 31.75, "length_mm": 15.7, "axis": "z"}


def test_preview_returns_both_ends_of_a_parameter(client, profile_id):
    response = client.post("/api/fingers/preview", json={"part": CAP, "cell_profile_id": profile_id, "choice": {}, "vary": "tip_height_mm"})

    assert response.status_code == 200
    body = response.json()
    assert [d["label"] for d in body["designs"]] == ["min", "max"]
    low, high = body["designs"]
    assert low["design"]["params"]["tip_height_mm"] < high["design"]["params"]["tip_height_mm"]
    for d in body["designs"]:
        assert d["problems"] == []
        finger = d["finger"]
        assert finger["pieces"] and finger["pieces"][0]["points"] and finger["pieces"][0]["triangles"]
        assert {"tip_height_mm", "jaw_close_mm", "jaw_open_mm", "contact_mm", "closed_gap_mm"} <= set(finger)
    assert body["free"][0] == "pad_width_mm"
    assert {"default_range", "limits", "effective_range", "note"} <= set(body["params"][0])


def test_preview_builds_given_designs(client, profile_id):
    designs = [{"kind": "imprint"}, {"kind": "search", "params": {"pad_width_mm": 20, "slack_mm": 3, "tip_height_mm": 4}}]

    response = client.post("/api/fingers/preview", json={"part": CAP, "cell_profile_id": profile_id, "designs": designs})

    assert response.status_code == 200
    assert [d["label"] for d in response.json()["designs"]] == ["0", "1"]


def test_varying_a_locked_parameter_is_a_422(client, profile_id):
    body = {"part": CAP, "cell_profile_id": profile_id, "choice": {"locks": {"slack_mm": 2}}, "vary": "slack_mm"}

    response = client.post("/api/fingers/preview", json=body)

    assert response.status_code == 422
    assert "it's locked" in response.json()["detail"]


def test_vary_and_designs_together_are_rejected(client, profile_id):
    body = {"part": CAP, "cell_profile_id": profile_id, "vary": "slack_mm", "designs": [{"kind": "imprint"}]}

    assert client.post("/api/fingers/preview", json=body).status_code == 422


def test_an_unknown_parameter_in_the_choice_is_rejected(client, profile_id):
    body = {"part": CAP, "cell_profile_id": profile_id, "choice": {"ranges": {"colour": {"lo": 1, "hi": 2}}}}

    assert client.post("/api/fingers/preview", json=body).status_code == 422


def test_an_unknown_cell_profile_is_a_404(client):
    response = client.post("/api/fingers/preview", json={"part": CAP, "cell_profile_id": 12345})

    assert response.status_code == 404
