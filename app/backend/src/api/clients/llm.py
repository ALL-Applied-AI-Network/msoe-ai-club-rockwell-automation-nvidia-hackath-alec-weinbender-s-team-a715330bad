"""The LLM step: proposes starting finger designs. Mock (default), Claude, or a custom HTTP service."""

import json
import logging
import random
import urllib.request
import zlib
from dataclasses import dataclass
from typing import Protocol

from api.config import LlmConfig
from api.models.design import SPACE, TEMPLATES
from api.models.part import Part

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
PROMPT = """You design 3D-printed parallel-jaw gripper fingers for a SCHUNK gripper.
Part (mm): {part}
Task: {task}
Choose {k} diverse starting designs. Templates and parameter ranges:
{space}
Reply with ONLY JSON: {{"suggestions":[{{"template":..., "params":{{...}}, "rationale":"..."}}]}}"""


@dataclass
class LlmReply:
    suggestions: list[dict]  # [{template, params, rationale}], not yet checked against SPACE
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
        suggestions = []
        for i in range(k):
            template = TEMPLATES[i % len(TEMPLATES)]
            params = {name: rng.uniform(lo, hi) for name, (lo, hi) in SPACE[template].items()}
            if template == "pocket":
                params["pocket_radius_scale"] = rng.uniform(0.9, 1.1)
            suggestions.append({"template": template, "params": params, "rationale": f"mock heuristic for ~{part.diameter_mm}mm part"})
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
        prompt = PROMPT.format(part=json.dumps(part.model_dump()), task=task, k=k, space=json.dumps(SPACE))
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
