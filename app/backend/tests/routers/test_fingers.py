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


# The finger library


def test_the_library_lists_fingers_without_their_geometry(evaluated_client, evaluated):
    response = evaluated_client.get("/api/fingers")

    assert response.status_code == 200
    listed = response.json()
    assert [f["code"] for f in listed] == ["FNG-0001", "FNG-0002", "FNG-0003"]
    assert all(f["pieces"] is None and f["built_for"] is None for f in listed)
    assert all(f["parts_evaluated"] == 1 and f["best_success"] is not None for f in listed)
    assert [f["id"] for f in evaluated_client.get("/api/fingers", params={"source": "uploaded"}).json()] == [evaluated.uploaded_id]


def test_a_finger_with_its_geometry(evaluated_client, evaluated):
    one = evaluated_client.get(f"/api/fingers/{evaluated.uploaded_id}")
    geometry = evaluated_client.get(f"/api/fingers/{evaluated.generated_id}/geometry")
    stock = evaluated_client.get(f"/api/fingers/{evaluated.stock_id}/geometry")

    assert one.status_code == 200 and one.json()["pieces"]
    assert geometry.status_code == 200 and geometry.json()["geometry"]["pieces"]
    assert stock.status_code == 200 and stock.json()["geometry"]["pieces"]
    assert evaluated_client.get("/api/fingers/nope").status_code == 404


def test_uploading_and_editing_a_finger(evaluated_copy_client, evaluated_copy, step_file):
    import cadquery as cq

    content = step_file(cq.Workplane("XY").box(12, 6, 76), "pad.step")
    form = {"cell_profile_id": evaluated_copy.profile_id, "name": "Rubber pad", "family": "flat", "material": "TPU"}
    form |= {"pad_friction_static": 0.9, "pad_friction_dynamic": 0.8, "quantity_on_hand": 2}

    created = evaluated_copy_client.post("/api/fingers", files={"finger_file": ("pad.step", content)}, data=form)

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["name"], body["material"], body["pad_friction"], body["quantity_on_hand"]) == ("Rubber pad", "TPU", [0.9, 0.8], 2)
    edited = evaluated_copy_client.patch(f"/api/fingers/{body['id']}", json={"archived": True, "notes": "worn"})
    assert edited.status_code == 200 and edited.json()["archived"] and edited.json()["notes"] == "worn"
    assert evaluated_copy_client.patch(f"/api/fingers/{body['id']}", json={"pieces": []}).status_code == 422
    half = form | {"pad_friction_dynamic": None}
    del half["pad_friction_dynamic"]
    assert evaluated_copy_client.post("/api/fingers", files={"finger_file": ("pad.step", content)}, data=half).status_code == 422
    assert evaluated_copy_client.post("/api/fingers", files={"finger_file": ("p.sldprt", b"x")}, data=form).status_code == 415
