"""Grasp simulation. Mock (default, a made-up grasp model) or the sim server running next to Isaac Sim.

Clients are sent to the optimizer's pool processes, so they must stay picklable: plain attributes, no open connections.
"""

import json
import logging
import math
import random
import urllib.request
from typing import Protocol

from api.config import SimConfig
from api.models.design import Design
from api.models.part import Part

logger = logging.getLogger(__name__)


class SimClient(Protocol):
    backend: str
    url: str | None

    def run_grasps(self, part: Part, design: Design, offsets: list[dict]) -> list[bool]:
        """One grasp per camera-error offset ({dx, dy, yaw_deg}); True where the part was held."""
        ...

    def close(self) -> None: ...


class MockSim:
    """Stand-in for the FANUC ER-4iA twin. Its success rates are invented: never report them as results."""

    backend = "mock"
    url = None

    def run_grasps(self, part: Part, design: Design, offsets: list[dict]) -> list[bool]:
        return [self._grasp(part, design, offset) for offset in offsets]

    def _grasp(self, part: Part, design: Design, offset: dict) -> bool:
        t, p, d = design.template, design.params, part.diameter_mm
        err = math.hypot(offset["dx"], offset["dy"])
        if t == "flat_pad":
            base = 0.62 + 0.25 * p["pad_friction_texture"] + 0.01 * min(p["pad_width"], d) / 4
            tol = 4 + p["pad_width"] / 6
        elif t == "v_groove":
            angle_fit = math.exp(-(((p["groove_angle"] - 95) / 30) ** 2))
            base = 0.55 + 0.4 * angle_fit * min(1, p["groove_depth"] / (0.25 * d))
            tol = 6 + p["groove_depth"] / 2
        else:
            clearance_fit = math.exp(-(((p["pocket_clearance"] - 1.5) / 2.5) ** 2))
            radius_fit = math.exp(-(((p["pocket_radius_scale"] - 1) / 0.15) ** 2))
            base = 0.5 + 0.35 * clearance_fit * radius_fit + 0.01 * min(p["pocket_depth"], d / 2)
            tol = 3 + p["pocket_depth"] / 4 + p["pocket_clearance"]
        reach = min(1.0, p["finger_length"] / (0.6 * d + 5))
        prob = base * reach * math.exp(-((err / tol) ** 2)) * math.exp(-((offset["yaw_deg"] / 25) ** 2))
        return random.random() < max(0.0, min(0.99, prob))

    def close(self) -> None:
        pass


class HttpSim:
    """The sim server (sim/sim_server). A whole batch is one request, so network and startup cost is paid once per batch."""

    backend = "http"

    def __init__(self, url: str, timeout_s: float):
        self.url, self.timeout_s = url, timeout_s

    def run_grasps(self, part: Part, design: Design, offsets: list[dict]) -> list[bool]:
        payload = {"part": part.model_dump(), "design": design.model_dump(), "offsets": offsets}
        request = urllib.request.Request(self.url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            return [bool(x) for x in json.loads(response.read())["successes"]]

    def close(self) -> None:
        pass


def create_sim_client(config: SimConfig) -> SimClient:
    client = HttpSim(config.url, config.timeout_s) if config.backend == "http" else MockSim()
    logger.info("Sim client: %s%s", client.backend, f" at {client.url}" if client.url else "")
    return client
