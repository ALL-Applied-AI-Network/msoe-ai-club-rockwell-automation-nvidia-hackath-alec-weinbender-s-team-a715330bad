"""An LLM that proposes starting finger designs. Mock (default), Claude, or a custom HTTP service.

The optimizer doesn't call it: round 0 is a Sobol sample of the search space. It's kept, on the new design parameters,
so suggestions can seed round 0 later if they turn out to help.
"""

import json
import logging
import random
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Protocol

from api.config import LlmConfig
from api.models.design import PARAMS
from api.models.part import Part
from api.models.search_space import SearchSpace

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v2"
PROMPT = """You design 3D-printed fingers for the parallel-jaw gripper on a FANUC ER-4iA: an SMC MHZL2-16D2 with 6 mm of
travel per jaw, gripping from above. A design is a contact pad described by these parameters (mm, degrees):
{space}
Part (mm, g): {part}
Task: {task}
Choose {k} diverse starting designs within those ranges.
Reply with ONLY JSON: {{"suggestions":[{{"params":{{...}}, "rationale":"..."}}]}}"""


@dataclass
class LlmReply:
    suggestions: list[dict]  # [{params, rationale}], not yet checked against the search space
    source: str  # the backend that answered
    model: str
    raw: str  # the verbatim response, kept so suggestions can be re-featurized later


class LlmClient(Protocol):
    backend: str

    def suggest(self, part: Part, task: str, k: int) -> LlmReply: ...

    def close(self) -> None: ...


class MockLlm:
    """Deterministic per part and task, and deliberately noisy, so there are good AND bad suggestions to learn from."""

    backend = "mock"

    def suggest(self, part: Part, task: str, k: int) -> LlmReply:
        rng = random.Random(zlib.crc32((json.dumps(part.model_dump(), sort_keys=True) + task).encode()))
        bounds = SearchSpace(part).bounds()
        suggestions = [
            {"params": {name: rng.uniform(lo, hi) for name, (lo, hi) in bounds.items()}, "rationale": f"mock guess for a {part.shape}"}
            for _ in range(k)
        ]
        return LlmReply(suggestions, "mock", "mock", json.dumps(suggestions))

    def close(self) -> None:
        pass


class AnthropicLlm:
    backend = "anthropic"

    def __init__(self, api_key: str, model: str):
        import anthropic  # imported here so the mock path and the optimizer's pool processes don't pay for it

        self.model = model
        self._client = anthropic.Anthropic(api_key=api_key)

    def suggest(self, part: Part, task: str, k: int) -> LlmReply:
        prompt = PROMPT.format(part=json.dumps(part.model_dump()), task=task, k=k, space=describe_space(part))
        message = self._client.messages.create(model=self.model, max_tokens=2000, messages=[{"role": "user", "content": prompt}])
        raw = message.content[0].text
        data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        return LlmReply(data["suggestions"][:k], "anthropic", self.model, raw)

    def close(self) -> None:
        self._client.close()


class HttpLlm:
    """A custom suggestion service: POST {part, task, k} -> {suggestions: [...], model?}."""

    backend = "http"

    def __init__(self, url: str, timeout_s: float = 600):
        self.url, self.timeout_s = url, timeout_s

    def suggest(self, part: Part, task: str, k: int) -> LlmReply:
        data = _post_json(self.url, {"part": part.model_dump(), "task": task, "k": k}, self.timeout_s)
        return LlmReply(data["suggestions"][:k], "http", data.get("model", "custom"), json.dumps(data))

    def close(self) -> None:
        pass


def describe_space(part: Part) -> str:
    """One line per design parameter: its range for this part and what it means."""
    return "\n".join(f"- {name} ({lo:.1f} to {hi:.1f}): {PARAMS[name]}" for name, (lo, hi) in SearchSpace(part).bounds().items())


def create_llm_client(config: LlmConfig) -> LlmClient:
    if config.backend == "anthropic":
        client = AnthropicLlm(config.api_key.get_secret_value(), config.model)
    elif config.backend == "http":
        client = HttpLlm(config.url)
    else:
        client = MockLlm()
    logger.info("LLM client: %s", client.backend)
    return client


def _post_json(url: str, payload: dict, timeout_s: float) -> dict:
    request = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read())
