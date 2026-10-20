import pytest

BOX = {"shape": "box", "width_mm": 10, "depth_mm": 10, "height_mm": 10}


def test_the_grid_preview_has_weighted_points_circles_and_yaw_layers(client):
    error = {"preset": "typical", "sigma_mm": 3, "sigma_deg": 8, "bias_mm": 1, "bias_direction_deg": 90}

    response = client.post("/api/grids", json={"part": BOX, "error": error})

    assert response.status_code == 200
    body = response.json()
    assert body["n_offsets"] == len(body["points"]) == 243
    assert body["yaws_deg"] == [-12, 0, 12]
    assert set(body["points"][0]) == {"dx", "dy", "yaw_deg", "weight"}
    assert sum(p["weight"] for p in body["points"]) == pytest.approx(body["coverage"])
    assert [c["label"] for c in body["circles"]] == ["1σ", "2σ"]
    assert body["circles"][0]["centre_mm"] == pytest.approx([0, 1])
    assert body["outer_ring_mm"] == 12 and body["warnings"] == []


def test_the_final_grid_is_denser(client):
    response = client.post("/api/grids", json={"part": {"shape": "cylinder"}, "final": True})

    assert response.status_code == 200 and response.json()["n_offsets"] == 321


def test_an_invalid_error_model_is_a_422(client):
    response = client.post("/api/grids", json={"part": BOX, "error": {"sigma_range_mm": [4, 1]}})

    assert response.status_code == 422
