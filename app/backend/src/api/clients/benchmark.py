"""Read-only simulator preflight for standalone experiments."""

import json
import urllib.request
from urllib.parse import urlparse


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("provide an HTTP(S) simulator URL without credentials, query or fragment")
    return url.rstrip("/")


def preflight(url: str) -> dict:
    with urllib.request.urlopen(f"{validate_url(url)}/health", timeout=5) as response:
        body = json.load(response)
    if not isinstance(body, dict) or body.get("status") != "ok" or not {"envs", "device", "friction_combine"} <= body.keys():
        raise ValueError("endpoint does not identify as the simulator health service")
    return body
