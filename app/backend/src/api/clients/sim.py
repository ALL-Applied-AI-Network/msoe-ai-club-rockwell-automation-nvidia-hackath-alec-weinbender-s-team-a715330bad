"""Grasp simulation. Mock (default: a geometric capture check) or the sim server running next to Isaac Sim.

A batch is designs x offsets: every design is tried at every camera-error offset, and the answer is one Outcomes per
design (held, the in-hand pose after the lift, held after transport). Fingers travel as geometry (convex pieces in the
gripper frame, see api/models/finger.py), so the sim server needs no knowledge of the design space; None stands for the
stock fingers already on the robot. The contract (v2) is section 5 of docs/notes/input-flow-backend-plan.md; the
server's side is sim/sim_server/src/sim_server/routers/evaluations.py.
"""

import base64
import http.client
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel

from api.config import SimConfig
from api.models.finger import Finger, Polygon, overlaps, sections, stock_finger, stock_grasp_pose
from api.models.job_spec import SimBackend
from api.models.outcome import InHand, Landing, Outcomes
from api.models.part import Part
from api.models.task import Transport

logger = logging.getLogger(__name__)

TALL = 1.5  # height / width above which a lead-in shoves a part over instead of sliding it in
MAX_SQUARING_DEG = 25  # flat pads square up a box turned less than this
FLAT_MM = 0.05  # a pad face set back less than this is flat: finer than a printer resolves
CENTRED: InHand = (0.0, 0.0, 0.0, 0.0, 0.0)
HEALTH_TIMEOUT_S = 5.0
RECONNECT_POLL_S = 10.0  # while a lost connection is down: how often to ask /health again
RETRY_STATUSES = (502, 503, 504)  # no server behind a proxy, or the server shutting down to restart


class SimError(RuntimeError):
    """The sim server couldn't run a batch, or couldn't be reached. The message says why, for the job's failure line."""


class SimResponseError(SimError):
    """The sim server's answer doesn't match the batch it was sent (missing rows, wrong lengths or types)."""


class _ConnectionLost(Exception):
    """The request or its answer was lost on the way, rather than the server refusing it: worth sending again. The
    message is the one to fail with."""


class SimSettings(BaseModel):
    """Per-batch settings from the cell profile and the task."""

    grip_force_n: float | None = None  # per-jaw force limit on the jaw drive; None: the twin's drive
    transport: Transport | None = None  # a quick move after the lift


class SimRecording(BaseModel):
    """One grasp filmed by the sim server (POST /record_grasp): its outcome and one mp4 per view."""

    held: bool
    in_hand: InHand | None
    held_after_transport: bool | None
    fps: int
    frames: int
    duration_s: float
    videos: dict[str, bytes]  # view ("closeup", "side") -> the mp4
    sim: dict[str, Any]


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

    def health(self) -> bool:
        """Is the sim answering? Never raises; the mock always is."""
        ...

    def record(self, part: Part, finger: Finger | None, offset: dict, settings: SimSettings, views: list[str]) -> SimRecording:
        """Film one grasp: the finger (None: stock) at one offset, simulated as run_batch would, with these camera views.
        The mock can't film: SimError."""
        ...

    def close(self) -> None: ...


class MockSim:
    """Stand-in for the FANUC ER-4iA twin, badged "mock" everywhere. Geometry only, no physics: it knows nothing about
    friction, force, mass or slip, so neither its success rates nor its in-hand poses are results. Never report them as
    predictions.

    A grasp holds if, with the jaws open, neither fingertip comes down on the part (a mesh part's own outline, through
    finger.overlaps()), a lead-in didn't have to shove a tall part sideways, a part that isn't round from above isn't
    turned past MAX_SQUARING_DEG, and the gripped part ends on the pads. For a section grip (Part.grip_span_mm) the pads
    must end on the section: the landing check already sees the whole part's outline (a screw's head too), and the
    width and overlap rules use the section's.

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

    def health(self) -> bool:
        return True

    def record(self, part: Part, finger: Finger | None, offset: dict, settings: SimSettings, views: list[str]) -> SimRecording:
        raise SimError("the mock sim has no physics or cameras to film a grasp with: clips need the Isaac sim")

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
    x, (near, far), height = part.grip_width, part.grip_span, part.extent_mm[2]
    lo, hi = float(face.ys[0]), float(face.ys[-1])
    if any(overlaps(p, part, offset) for p in tips):
        return False  # a fingertip comes down on the part
    if height > TALL * x and any(overlaps(p, part, offset) for p in faces):
        return False  # only the lead-in caught it, and it tips a tall part over
    if not part.round_from_above and abs(offset.get("yaw_deg", 0.0)) > MAX_SQUARING_DEG:
        return False  # turned too far for the pads to square it up
    if part.round_from_above:
        return lo + 0.5 <= offset["dy"] <= hi - 0.5  # the contact line lands on the pad
    return min(hi, offset["dy"] + far) - max(lo, offset["dy"] + near) >= 2.0


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
    once per round. Holds plain attributes only, so it pickles into the optimizer's process pool.

    A long run outlives a dropped connection (the VPN, the GPU's port forward, which the GPU session reopens): once the
    server has answered, a batch whose request or answer is lost waits up to reconnect_s for /health to answer again and
    is sent again under the same Idempotency-Key, so the server answers from the run it made, or is still making, instead
    of running it twice. Until the server has answered, a failure is a wrong SIM_URL or a GPU that isn't connected, and
    fails at once."""

    backend = "http"
    badge: SimBackend = "isaac"

    def __init__(
        self,
        url: str,
        timeout_s: float,
        reconnect_s: float = 0.0,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.url, self.timeout_s, self.reconnect_s = url.rstrip("/"), timeout_s, reconnect_s
        self._sleep, self._clock = sleep, clock
        self._last_sim: dict[str, Any] = {}
        self._answered = False  # has the server answered this process? Only then is a failed request a lost connection

    def run_batch(self, part: Part, fingers: list[Finger | None], offsets: list[dict], settings: SimSettings) -> list[Outcomes]:
        payload = {
            "part": _part_payload(part),
            "designs": [_design_payload(i, f, part) for i, f in enumerate(fingers)],
            "offsets": [{"dx": float(o["dx"]), "dy": float(o["dy"]), "yaw_deg": float(o.get("yaw_deg", 0.0))} for o in offsets],
            "grip_force_n": settings.grip_force_n,
            "transport": settings.transport,
        }
        logger.debug("Sim batch: %d designs x %d offsets to %s", len(fingers), len(offsets), self.url)
        if self.reconnect_s and not self._answered:
            self.health()  # an answer here makes a connection lost during this first batch worth waiting for
        body = self._post("/evaluate_batch", payload)
        outcomes = _outcomes(body, len(fingers), len(offsets), transport=settings.transport is not None)
        sim = body.get("sim")
        self._last_sim = dict(sim) if isinstance(sim, dict) else {}
        return outcomes

    def describe(self) -> dict[str, Any]:
        """The server's `sim` block from the last batch (envs, device, physics_dt, friction_combine, ...) and its URL."""
        return {**self._last_sim, "url": self.url}

    def health(self) -> bool:
        """GET {url}/health answers {"status": "ok"}."""
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=HEALTH_TIMEOUT_S) as response:
                ok = json.loads(response.read()).get("status") == "ok"
        except (OSError, http.client.HTTPException, ValueError, AttributeError):  # unreachable, cut off, not JSON, not an object
            return False
        self._answered = self._answered or ok
        return ok

    def record(self, part: Part, finger: Finger | None, offset: dict, settings: SimSettings, views: list[str]) -> SimRecording:
        """POST {url}/record_grasp: the grasp run_batch would simulate for this finger at this offset, filmed. A lost
        connection is retried as a batch's is; the server films it again."""
        payload = {
            "part": _part_payload(part),
            "design": _design_payload(0, finger, part),
            "offset": {"dx": float(offset["dx"]), "dy": float(offset["dy"]), "yaw_deg": float(offset.get("yaw_deg", 0.0))},
            "grip_force_n": settings.grip_force_n,
            "transport": settings.transport,
            "views": list(views),
        }
        if self.reconnect_s and not self._answered:
            self.health()
        body = self._post("/record_grasp", payload)
        videos = body.get("videos")
        if not isinstance(videos, dict) or not videos:
            raise SimResponseError(f"the sim server at {self.url} answered a recording without videos")
        try:
            decoded = {str(view): base64.b64decode(data, validate=True) for view, data in videos.items()}
            held = _flag(body.get("held"), "held")
            after = body.get("held_after_transport")
            return SimRecording(
                held=held,
                in_hand=_pose(body.get("in_hand")) if held else None,
                held_after_transport=None if after is None else _flag(after, "held_after_transport"),
                fps=int(body.get("fps", 30)),
                frames=int(body.get("frames", 0)),
                duration_s=float(body.get("duration_s", 0.0)),
                videos=decoded,
                sim=dict(body.get("sim") or {}),
            )
        except (TypeError, ValueError) as e:  # base64, or a number that isn't one
            raise SimResponseError(f"the sim server at {self.url} answered a recording it can't be read from: {e}") from e

    def close(self) -> None:
        pass

    def _post(self, path: str, payload: dict) -> dict:
        data, key = json.dumps(payload).encode(), uuid.uuid4().hex
        deadline = None
        while True:
            try:
                raw = self._send(path, data, key)
                break
            except _ConnectionLost as e:
                if not (self.reconnect_s and self._answered):
                    raise SimError(str(e)) from e
                if deadline is None:
                    deadline = self._clock() + self.reconnect_s
                    logger.warning("%s; waiting up to %g min for it to answer again", e, self.reconnect_s / 60)
                if not self._wait_for_health(deadline):
                    raise SimError(
                        f"{e}, and it didn't answer again within {self.reconnect_s / 60:g} min: reconnect the GPU in the GPU "
                        "panel, then resume the job"
                    ) from e
                logger.info("The sim server at %s answers again; sending the batch again", self.url)
        self._answered = True
        try:
            body = json.loads(raw)
        except ValueError as e:
            raise SimResponseError(f"the sim server at {self.url} didn't answer with JSON") from e
        if not isinstance(body, dict):
            raise SimResponseError(f"the sim server at {self.url} answered with a JSON {type(body).__name__}, not an object")
        return body

    def _send(self, path: str, data: bytes, key: str) -> bytes:
        """One POST. _ConnectionLost when the request or its answer was lost on the way; SimError when the server
        refused it or took longer than timeout_s."""
        headers = {"Content-Type": "application/json", "Idempotency-Key": key}
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{self.url}{path}", data, headers), timeout=self.timeout_s) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            message = f"the sim server at {self.url} answered {e.code}: {_error_detail(e)}"
            if e.code in RETRY_STATUSES:
                raise _ConnectionLost(message) from e
            raise SimError(message) from e
        except TimeoutError as e:
            raise SimError(f"the sim server at {self.url} didn't answer within {self.timeout_s:g} s") from e
        except urllib.error.URLError as e:
            raise _ConnectionLost(f"can't reach the sim server at {self.url}: {e.reason}") from e
        except (OSError, http.client.HTTPException) as e:  # reset, or cut off mid-answer: the forward went down
            raise _ConnectionLost(f"lost the connection to the sim server at {self.url}: {e or type(e).__name__}") from e

    def _wait_for_health(self, deadline: float) -> bool:
        """Ask /health every RECONNECT_POLL_S until it answers (True) or the deadline has passed (False). It's asked at
        least once, so a laptop that slept past the deadline still finds a server that's back."""
        while True:
            self._sleep(RECONNECT_POLL_S)
            if self.health():
                return True
            if self._clock() >= deadline:
                return False


def create_sim_client(config: SimConfig) -> SimClient:
    client = HttpSim(config.url, config.timeout_s, config.reconnect_minutes * 60) if config.backend == "http" else MockSim()
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
        if part.grip_width_mm is None:
            return {"id": "stock"}
        # The server's stock rule closes on the whole part's width: a section grip (a screw's shank) closes further.
        return {"id": "stock", "jaw_close_mm": stock_grasp_pose(part)["jaw_close_mm"]}
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
    the batch asked for a transport move, and must be there then. landing (how far the part moved before the jaws
    closed) is None from a server that doesn't report it (before 2026-10-26)."""
    held = _grid(body.get("held"), "held", n_designs, n_offsets)
    if held is None:
        raise SimResponseError("the sim server's answer has no 'held'")
    in_hand = _grid(body.get("in_hand"), "in_hand", n_designs, n_offsets)
    after = _grid(body.get("held_after_transport"), "held_after_transport", n_designs, n_offsets) if transport else None
    landing = _grid(body.get("landing"), "landing", n_designs, n_offsets)
    out = []
    for d in range(n_designs):
        row = [_flag(v, "held") for v in held[d]]
        poses = [None if in_hand is None or not row[i] else _pose(in_hand[d][i]) for i in range(n_offsets)]
        out.append(
            Outcomes(
                held=row,
                in_hand=poses,
                held_after_transport=None if after is None else [_flag(v, "held_after_transport") for v in after[d]],
                landing=None if landing is None else [_landing(v) for v in landing[d]],
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


def _landing(value: Any) -> Landing | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 2 or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value):
        raise SimResponseError(f"the sim server answered {value!r} as a landing, not [shift_mm, turn_deg]")
    return float(value[0]), float(value[1])


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
