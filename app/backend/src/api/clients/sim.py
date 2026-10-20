"""Grasp simulation. Mock (default: a geometric capture check) or the sim server running next to Isaac Sim.

A batch is designs x offsets: every design is tried at every camera-error offset, and the answer is one Outcomes per
design (held, the in-hand pose after the lift, held after transport). Fingers travel as geometry (convex pieces in the
gripper frame, see api/models/finger.py), so the sim server needs no knowledge of the design space; None stands for the
stock fingers already on the robot. The contract (v2) is section 5 of docs/notes/input-flow-backend-plan.md; the
server's side is sim/sim_server/src/sim_server/routers/evaluations.py.
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel

from api.config import SimConfig
from api.models.finger import Finger, Polygon, overlaps, sections, stock_finger
from api.models.job_spec import SimBackend
from api.models.outcome import InHand, Outcomes
from api.models.part import Part
from api.models.task import Transport

logger = logging.getLogger(__name__)

TALL = 1.5  # height / width above which a lead-in shoves a part over instead of sliding it in
MAX_SQUARING_DEG = 25  # flat pads square up a box turned less than this
FLAT_MM = 0.05  # a pad face set back less than this is flat: finer than a printer resolves
CENTRED: InHand = (0.0, 0.0, 0.0, 0.0, 0.0)


class SimError(RuntimeError):
    """The sim server couldn't run a batch, or couldn't be reached. The message says why, for the job's failure line."""


class SimResponseError(SimError):
    """The sim server's answer doesn't match the batch it was sent (missing rows, wrong lengths or types)."""


class SimSettings(BaseModel):
    """Per-batch settings from the cell profile and the task."""

    grip_force_n: float | None = None  # per-jaw force limit on the jaw drive; None: the twin's drive
    transport: Transport | None = None  # a quick move after the lift


class SimClient(Protocol):
    backend: str  # "mock" or "http"
    badge: SimBackend  # what results are labelled with: "mock" or "isaac"
    url: str | None

    def run_batch(self, part: Part, fingers: list[Finger | None], offsets: list[dict], settings: SimSettings) -> list[Outcomes]:
        """One Outcomes per finger (None: the stock fingers), with one entry per camera-error offset ({dx, dy, yaw_deg}
        in mm and degrees, in the gripper's frame)."""
        ...

    def describe(self) -> dict[str, Any]:
        """What the sim ran with (environments, device, physics settings), for run metadata. Empty for the mock."""
        ...

    def close(self) -> None: ...


class MockSim:
    """Stand-in for the FANUC ER-4iA twin, badged "mock" everywhere. Geometry only, no physics: it knows nothing about
    friction, force, mass or slip, so neither its success rates nor its in-hand poses are results. Never report them as
    predictions.

    A grasp holds if, with the jaws open, neither fingertip comes down on the part (a mesh part's own outline, through
    finger.overlaps()), a lead-in didn't have to shove a tall part sideways, a part that isn't round from above isn't
    turned past MAX_SQUARING_DEG, and the gripped part ends on the pads.

    In-hand pose of a held part (dx, dy, dz, tilt, yaw; see api/models/outcome.py), from the pad face's cross-section
    (a Finger carries geometry, not its design's params):
    - dx -> 0: both pads squeeze the part to the centre.
    - dy: a round part (Part.round_from_above) whose centre lands within a groove's mouth (where the face is set back
      from its front) settles to the groove's bottom: every point it can touch there is on a flank or the mouth's edge,
      and pushes it toward the bottom. Landing on a flat stretch, any part stays at the offset's dy.
    - yaw -> 0 for a box or lying cylinder (a rectangle from above) between flat pads, turned at most MAX_SQUARING_DEG:
      closing flat jaws turn it flush. It's 0 for a round part, whose yaw doesn't show. Otherwise (grooved pads on a
      rectangle, any mesh part) it stays at the offset's yaw: nothing here says how it would turn.
    - tilt and dz are 0: nothing here tips or drops a part.
    Held after transport = held, when the task adds a transport move: the mock has no inertia.
    """

    backend = "mock"
    badge: SimBackend = "mock"
    url = None

    def run_batch(self, part: Part, fingers: list[Finger | None], offsets: list[dict], settings: SimSettings) -> list[Outcomes]:
        return [self._outcomes(part, finger or stock_finger(part), offsets, settings.transport is not None) for finger in fingers]

    def describe(self) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        pass

    def _outcomes(self, part: Part, finger: Finger, offsets: list[dict], transport: bool) -> Outcomes:
        _, _, height = part.extent_mm
        part_top = height - finger.tip_height_mm  # in the gripper frame, where the fingertips are at 0
        if finger.contact_mm < 2 or part_top <= 0:
            return Outcomes.dropped(len(offsets), transport)
        tips = sections(finger, 1e-6, finger.jaw_open_mm)
        faces = sections(finger, part_top - 1e-6, finger.jaw_open_mm)  # above any lead-in: the straight pad face
        face = _PadFace.of(faces)
        in_hand = [_in_hand(part, face, offset) if _held(part, tips, faces, face, offset) else None for offset in offsets]
        held = [pose is not None for pose in in_hand]
        return Outcomes(held=held, in_hand=in_hand, held_after_transport=list(held) if transport else None)


@dataclass(frozen=True)
class _PadFace:
    """One finger's pad face across the jaws, at one height: its breakpoints along y and how far the face is set back
    from its front at each. The other finger is its mirror image in x, so it has the same face."""

    ys: np.ndarray
    recess: np.ndarray

    @classmethod
    def of(cls, polygons: list[Polygon]) -> "_PadFace":
        """From both fingers' cross-sections (finger.sections()) with the jaws open, where this finger is all at +x."""
        ours = [polygon for polygon in polygons if sum(x for x, _ in polygon) > 0]
        ys = np.unique(np.round([y for polygon in ours for _, y in polygon], 6))
        xs = np.array([min(x for polygon in ours if (x := _inner_x(polygon, y)) is not None) for y in ys])
        return cls(ys, xs - xs.min())

    @property
    def flat(self) -> bool:
        return float(self.recess.max()) < FLAT_MM

    def groove_bottom(self, y: float) -> float | None:
        """Where a round part whose centre lands at y settles: the deepest point of the groove whose mouth it lands in.
        None where the face isn't set back at y (it stays where it landed)."""
        ys, recess, eps = self.ys, self.recess, 1e-9
        if self.flat or not ys[0] < y < ys[-1] or np.interp(y, ys, recess) <= eps:
            return None
        hi = int(np.searchsorted(ys, y))  # ys[hi - 1] < y <= ys[hi]
        lo = hi - 1
        while lo > 0 and recess[lo] > eps:
            lo -= 1
        while hi < len(ys) - 1 and recess[hi] > eps:
            hi += 1
        mouth = slice(lo, hi + 1)
        deepest = recess[mouth].max()
        if deepest < FLAT_MM:
            return None
        return float(ys[mouth][recess[mouth] >= deepest - eps].mean())


def _held(part: Part, tips: list[Polygon], faces: list[Polygon], face: _PadFace, offset: dict) -> bool:
    x, y, height = part.extent_mm
    lo, hi = float(face.ys[0]), float(face.ys[-1])
    if any(overlaps(p, part, offset) for p in tips):
        return False  # a fingertip comes down on the part
    if height > TALL * x and any(overlaps(p, part, offset) for p in faces):
        return False  # only the lead-in caught it, and it tips a tall part over
    if not part.round_from_above and abs(offset.get("yaw_deg", 0.0)) > MAX_SQUARING_DEG:
        return False  # turned too far for the pads to square it up
    if part.round_from_above:
        return lo + 0.5 <= offset["dy"] <= hi - 0.5  # the contact line lands on the pad
    return min(hi, offset["dy"] + y / 2) - max(lo, offset["dy"] - y / 2) >= 2.0


def _in_hand(part: Part, face: _PadFace, offset: dict) -> InHand:
    """The mock's in-hand estimate for a held part (the rules are in MockSim's docstring)."""
    dy, yaw = float(offset["dy"]), float(offset.get("yaw_deg", 0.0))
    if part.round_from_above:
        bottom = face.groove_bottom(dy)
        return (0.0, dy if bottom is None else bottom, 0.0, 0.0, 0.0)
    if part.shape != "mesh" and face.flat and abs(yaw) <= MAX_SQUARING_DEG:
        yaw = 0.0
    return (0.0, dy, 0.0, 0.0, yaw)


def _inner_x(polygon: Polygon, y: float, eps: float = 1e-6) -> float | None:
    """The convex polygon's smallest x along the line at this y; None if the line misses it."""
    xs = []
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if min(ay, by) - eps <= y <= max(ay, by) + eps:
            if abs(by - ay) <= eps:
                xs += [ax, bx]
            else:
                t = min(1.0, max(0.0, (y - ay) / (by - ay)))
                xs.append(ax + t * (bx - ax))
    return min(xs) if xs else None


class HttpSim:
    """The sim server (sim/sim_server) at a base URL. A whole round is one request, so startup and network cost is paid
    once per round. Holds plain attributes only, so it pickles into the optimizer's process pool."""

    backend = "http"
    badge: SimBackend = "isaac"

    def __init__(self, url: str, timeout_s: float):
        self.url, self.timeout_s = url.rstrip("/"), timeout_s
        self._last_sim: dict[str, Any] = {}

    def run_batch(self, part: Part, fingers: list[Finger | None], offsets: list[dict], settings: SimSettings) -> list[Outcomes]:
        payload = {
            "part": _part_payload(part),
            "designs": [_design_payload(i, f, part) for i, f in enumerate(fingers)],
            "offsets": [{"dx": float(o["dx"]), "dy": float(o["dy"]), "yaw_deg": float(o.get("yaw_deg", 0.0))} for o in offsets],
            "grip_force_n": settings.grip_force_n,
            "transport": settings.transport,
        }
        logger.debug("Sim batch: %d designs x %d offsets to %s", len(fingers), len(offsets), self.url)
        body = self._post("/evaluate_batch", payload)
        outcomes = _outcomes(body, len(fingers), len(offsets), transport=settings.transport is not None)
        sim = body.get("sim")
        self._last_sim = dict(sim) if isinstance(sim, dict) else {}
        return outcomes

    def describe(self) -> dict[str, Any]:
        """The server's `sim` block from the last batch (envs, device, physics_dt, friction_combine, ...) and its URL."""
        return {**self._last_sim, "url": self.url}

    def close(self) -> None:
        pass

    def _post(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(f"{self.url}{path}", json.dumps(payload).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read()
        except urllib.error.HTTPError as e:
            raise SimError(f"the sim server at {self.url} answered {e.code}: {_error_detail(e)}") from e
        except urllib.error.URLError as e:
            raise SimError(f"can't reach the sim server at {self.url}: {e.reason}") from e
        except TimeoutError as e:
            raise SimError(f"the sim server at {self.url} didn't answer within {self.timeout_s:g} s") from e
        try:
            body = json.loads(raw)
        except ValueError as e:
            raise SimResponseError(f"the sim server at {self.url} didn't answer with JSON") from e
        if not isinstance(body, dict):
            raise SimResponseError(f"the sim server at {self.url} answered with a JSON {type(body).__name__}, not an object")
        return body


def create_sim_client(config: SimConfig) -> SimClient:
    client = HttpSim(config.url, config.timeout_s) if config.backend == "http" else MockSim()
    logger.info("Sim client: %s%s", client.backend, f" at {client.url}" if client.url else "")
    return client


def sim_badge(backend: str) -> SimBackend:
    """The badge results from a SIM_BACKEND get, without building the client: "mock", or "isaac" for the sim server."""
    return HttpSim.badge if backend == "http" else MockSim.badge


def _part_payload(part: Part) -> dict:
    """The sim server's part: the fields of its shape (a box's sizes as box_mm [along the jaws, across, height]), its
    mass, and its friction pair against the printed pads (D7)."""
    payload: dict[str, Any] = {"shape": part.shape}
    if part.shape == "cylinder":
        payload |= {"diameter_mm": part.diameter_mm, "length_mm": part.length_mm, "axis": part.axis}
    elif part.shape == "box":
        payload["box_mm"] = [part.width_mm, part.depth_mm, part.height_mm]
    else:
        payload["pieces"] = [piece.model_dump() for piece in part.pieces]
    return payload | {"mass_g": part.mass_g, "friction": list(part.friction)}


def _design_payload(i: int, finger: Finger | None, part: Part) -> dict:
    if finger is None:
        return {"id": "stock"}
    return {
        "id": f"d{i}",
        "pieces": [piece.model_dump() for piece in finger.pieces],
        "friction": list(part.friction),  # the part's pair coefficient on both sides: exact under any combine but multiply
        "tip_height_mm": finger.tip_height_mm,
        "jaw_close_mm": finger.jaw_close_mm,
    }


def _outcomes(body: dict, n_designs: int, n_offsets: int, *, transport: bool) -> list[Outcomes]:
    """The server's answer as one Outcomes per design, checked against the batch's shape. A server that doesn't report
    in_hand (v1) leaves every pose None; one held as False has no pose either. held_after_transport is read only when
    the batch asked for a transport move, and must be there then."""
    held = _grid(body.get("held"), "held", n_designs, n_offsets)
    if held is None:
        raise SimResponseError("the sim server's answer has no 'held'")
    in_hand = _grid(body.get("in_hand"), "in_hand", n_designs, n_offsets)
    after = _grid(body.get("held_after_transport"), "held_after_transport", n_designs, n_offsets) if transport else None
    out = []
    for d in range(n_designs):
        row = [_flag(v, "held") for v in held[d]]
        poses = [None if in_hand is None or not row[i] else _pose(in_hand[d][i]) for i in range(n_offsets)]
        out.append(
            Outcomes(
                held=row,
                in_hand=poses,
                held_after_transport=None if after is None else [_flag(v, "held_after_transport") for v in after[d]],
            )
        )
    if transport and after is None:
        # Scored without it, every grasp that held through the lift would count as held through transport too.
        raise SimResponseError("a transport move was asked for, but the sim server didn't report held_after_transport (a pre-v2 server?)")
    return out


def _grid(value: Any, name: str, n_designs: int, n_offsets: int) -> list[list[Any]] | None:
    """A designs x offsets array from the answer, or None where it's missing or null."""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != n_designs or any(not isinstance(row, list) or len(row) != n_offsets for row in value):
        if isinstance(value, list):
            lengths = sorted({str(len(row)) if isinstance(row, list) else "-" for row in value})
            shape = f"{len(value)} x {'/'.join(lengths) or 0}"
        else:
            shape = f"a {type(value).__name__}"
        raise SimResponseError(f"the sim server answered {name} as {shape} for {n_designs} designs x {n_offsets} offsets")
    return value


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool | int):
        raise SimResponseError(f"the sim server answered {value!r} in {name}, not true or false")
    return bool(value)


def _pose(value: Any) -> InHand | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 5 or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value):
        raise SimResponseError(f"the sim server answered {value!r} as an in-hand pose, not [dx, dy, dz, tilt, yaw]")
    return tuple(float(v) for v in value)


def _error_detail(error: urllib.error.HTTPError) -> str:
    """FastAPI's error body {"detail": ...} as one line, or the raw text."""
    try:
        text = error.read().decode("utf-8", "replace")
    except OSError:
        return error.reason or "no detail"
    try:
        detail = json.loads(text).get("detail", text)
    except (ValueError, AttributeError):
        detail = text
    return (detail if isinstance(detail, str) else json.dumps(detail))[:500]
