import json

import pytest


@pytest.mark.parametrize("dataset", ["trials", "suggestions", "physical"])
def test_exports_are_json_lines(finished_client, dataset):
    response = finished_client.get(f"/api/export/{dataset}.jsonl")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/x-ndjson"
    rows = [json.loads(line) for line in response.text.splitlines()]
    assert all(isinstance(row, dict) for row in rows)
