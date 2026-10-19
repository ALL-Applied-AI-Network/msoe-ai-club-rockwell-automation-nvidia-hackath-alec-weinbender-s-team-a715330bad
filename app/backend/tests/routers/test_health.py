def test_health(client):
    response = client.get("/health")

    assert (response.status_code, response.json()) == (200, {"status": "ok"})
