from api.clients.llm import HttpLlm, MockLlm, create_llm_client, describe_space
from api.config import LlmConfig
from api.models.part import Part
from api.models.search_space import SearchSpace


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


def test_mock_suggestions_stay_inside_the_parts_search_space():
    part = Part()
    reply = MockLlm().suggest(part, "pick", 6)

    assert len(reply.suggestions) == 6
    for s in reply.suggestions:
        for name, (lo, hi) in SearchSpace(part).bounds().items():
            assert lo <= s["params"][name] <= hi


def test_the_prompt_describes_every_parameter_with_its_range():
    lines = describe_space(Part(shape="box")).splitlines()

    assert [line.split(" ")[1] for line in lines] == SearchSpace(Part(shape="box")).names
