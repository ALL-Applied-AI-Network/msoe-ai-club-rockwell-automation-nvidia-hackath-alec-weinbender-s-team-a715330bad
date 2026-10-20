from api.models.design import PARAMS


def test_meta_lists_the_design_parameters_and_active_backends(client):
    meta = client.get("/api/meta").json()

    assert meta["parameters"] == PARAMS
    assert (meta["llm"], meta["sim"]) == ("mock", "mock")
