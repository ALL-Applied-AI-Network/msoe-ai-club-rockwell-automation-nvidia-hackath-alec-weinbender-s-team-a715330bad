from api.clients.llm import HttpLlm, MockLlm, create_llm_client
from api.config import LlmConfig
from api.models.design import SPACE
from api.models.part import Part


def test_factory_builds_the_configured_backend():
    assert isinstance(create_llm_client(LlmConfig(backend="mock")), MockLlm)
    client = create_llm_client(LlmConfig(backend="http", url="http://llm:9100/suggest"))
    assert isinstance(client, HttpLlm)
    assert client.url == "http://llm:9100/suggest"


def test_mock_is_deterministic_per_part_and_task():
    part = Part(diameter_mm=12)

    first, second = MockLlm().suggest(part, "sort caps", 6), MockLlm().suggest(part, "sort caps", 6)

    assert first == second
    assert MockLlm().suggest(part, "stack cubes", 6).suggestions != first.suggestions


def test_mock_suggestions_stay_inside_the_design_space():
    reply = MockLlm().suggest(Part(), "pick", 6)

    assert len(reply.suggestions) == 6
    for s in reply.suggestions:
        for name, (lo, hi) in SPACE[s["template"]].items():
            assert lo <= s["params"][name] <= hi
