from api.models.design import SPACE


def test_meta_lists_the_design_space_and_active_backends(client):
    meta = client.get("/api/meta").json()

    assert meta["templates"].keys() == SPACE.keys()
    assert meta["templates"]["pocket"]["pocket_depth"] == [2, 25]
    assert (meta["llm"], meta["sim"]) == ("mock", "mock")
