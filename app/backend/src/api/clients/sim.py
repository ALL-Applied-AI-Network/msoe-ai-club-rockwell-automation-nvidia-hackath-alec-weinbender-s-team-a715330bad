"""Grasp simulation. Mock (default: a geometric capture check) or the sim server running next to Isaac Sim.

A batch is designs x offsets: every design is tried at every camera-error offset, and the answer is one row of held/not
held per design. Fingers travel as geometry (convex pieces in the gripper frame, see api/models/finger.py), so the sim
server needs no knowledge of the design space; None stands for the stock fingers already on the robot.
"""

import json
import logging
import urllib.request
from typing import Protocol

from api.config import SimConfig
from api.models.finger import STROKE_MM, Finger, overlaps, sections, stock_finger
from api.models.part import Part

logger = logging.getLogger(__name__)

TALL = 1.5  # height / width above which a lead-in shoves a part over instead of sliding it in
MAX_SQUARING_DEG = 25  # flat pads square up a box turned less than this


class SimClient(Protocol):
    backend: str
    url: str | None

    def run_batch(self, part: Part, fingers: list[Finger | None], offsets: list[dict]) -> list[list[bool]]:
        """One row per finger (None: the stock fingers), one bool per camera-error offset ({dx, dy, yaw_deg} in mm and
        degrees, in the gripper's frame): True where the part was held."""
        ...

    def close(self) -> None: ...


class MockSim:
    """Stand-in for the FANUC ER-4iA twin. Geometry only, no physics: a grasp holds if, with the jaws open, neither
    finger comes down on the part, a lead-in didn't have to shove a tall part sideways, a box isn't turned too far for
    flat pads to square it up, and the gripped part ends on the pads. It knows nothing about friction, force or slip, so
    its success rates are not results: never report them."""

    backend = "mock"
    url = None

    def run_batch(self, part: Part, fingers: list[Finger | None], offsets: list[dict]) -> list[list[bool]]:
        return [self._row(part, finger or stock_finger(part), offsets) for finger in fingers]

    def _row(self, part: Part, finger: Finger, offsets: list[dict]) -> list[bool]:
        x, y, height = part.extent_mm
        part_top = height - finger.tip_height_mm  # in the gripper frame, where the fingertips are at 0
        if finger.contact_mm < 2 or part_top <= 0:
            return [False] * len(offsets)
        tips, faces = sections(finger, 1e-6, STROKE_MM), sections(finger, part_top - 1e-6, STROKE_MM)
        pad_ys = [py for polygon in faces for _, py in polygon]
        lo, hi = min(pad_ys), max(pad_ys)
        row = []
        for offset in offsets:
            if any(overlaps(p, part, offset) for p in tips):
                row.append(False)  # a fingertip comes down on the part
            elif height > TALL * x and any(overlaps(p, part, offset) for p in faces):
                row.append(False)  # only the lead-in caught it, and it tips a tall part over
            elif not part.round_from_above and abs(offset.get("yaw_deg", 0.0)) > MAX_SQUARING_DEG:
                row.append(False)
            elif part.round_from_above:
                row.append(lo + 0.5 <= offset["dy"] <= hi - 0.5)  # the contact line lands on the pad
            else:
                row.append(min(hi, offset["dy"] + y / 2) - max(lo, offset["dy"] - y / 2) >= 2.0)
        return row

    def close(self) -> None:
        pass


class HttpSim:
    """The sim server (sim/sim_server) at a base URL. A whole round is one request, so startup and network cost is paid
    once per round."""

    backend = "http"

    def __init__(self, url: str, timeout_s: float):
        self.url, self.timeout_s = url.rstrip("/"), timeout_s

    def run_batch(self, part: Part, fingers: list[Finger | None], offsets: list[dict]) -> list[list[bool]]:
        payload = {"part": _part_payload(part), "designs": [_design_payload(i, f) for i, f in enumerate(fingers)], "offsets": offsets}
        request = urllib.request.Request(f"{self.url}/evaluate_batch", json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            held = [[bool(v) for v in row] for row in json.loads(response.read())["held"]]
        if len(held) != len(fingers) or any(len(row) != len(offsets) for row in held):
            raise ValueError(f"the sim server answered {len(held)} rows for {len(fingers)} designs x {len(offsets)} offsets")
        return held

    def close(self) -> None:
        pass


def create_sim_client(config: SimConfig) -> SimClient:
    client = HttpSim(config.url, config.timeout_s) if config.backend == "http" else MockSim()
    logger.info("Sim client: %s%s", client.backend, f" at {client.url}" if client.url else "")
    return client


def _part_payload(part: Part) -> dict:
    """The sim server's part fields: a box's sizes travel as box_mm [along the jaws, across, height]."""
    return {
        "shape": part.shape,
        "diameter_mm": part.diameter_mm,
        "length_mm": part.length_mm,
        "upright": part.upright,
        "box_mm": [part.width_mm, part.depth_mm, part.height_mm],
        "mass_g": part.mass_g,
    }


def _design_payload(i: int, finger: Finger | None) -> dict:
    if finger is None:
        return {"id": "stock"}
    return {
        "id": f"d{i}",
        "pieces": [piece.model_dump() for piece in finger.pieces],
        "friction": list(finger.friction),
        "tip_height_mm": finger.tip_height_mm,
        "jaw_close_mm": finger.jaw_close_mm,
    }
