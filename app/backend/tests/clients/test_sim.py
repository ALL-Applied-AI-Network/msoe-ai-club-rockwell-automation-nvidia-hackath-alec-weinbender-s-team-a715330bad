import base64
import json
import pickle
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from api.clients.sim import HttpSim, MockSim, SimError, SimResponseError, SimSettings, create_sim_client, sim_badge
from api.config import SimConfig
from api.models.design import Design
from api.models.finger import build_finger
from api.models.part import Part
from api.models.piece import Piece, hull_piece

CAP, CUBE = Part(), Part(shape="box")
WIDE_SLACK = {"pad_width_mm": 30, "groove_angle_deg": 180, "groove_depth_mm": 0, "slack_mm": 5, "tip_height_mm": 3, "lead_in_mm": 2}
FLAT = {"pad_width_mm": 20, "slack_mm": 3, "tip_height_mm": 4}
V_GROOVE = {**FLAT, "groove_angle_deg": 90, "groove_depth_mm": 3}  # its mouth spans y -3..3
CENTRED, FAR = {"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}, {"dx": 9.0, "dy": 0.0, "yaw_deg": 0.0}
NO_TRANSPORT = SimSettings()


def at(dx=0.0, dy=0.0, yaw_deg=0.0) -> dict:
    return {"dx": dx, "dy": dy, "yaw_deg": yaw_deg}


def block(x0, x1, y0, y1, z0=0.0, z1=10.0) -> Piece:
    return hull_piece([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])


# Seen from above, an I: a 16 mm wide waist between 20 mm wide flanges at each end. Its bounding box is 20 x 24 x 10.
I_BEAM = Part(shape="mesh", pieces=[block(-8, 8, -12, 12), block(-10, 10, 8, 12), block(-10, 10, -12, -8)])


@contextmanager
def stand_in(answer, status=200):
    """A stand-in for sim/sim_server: records each request and replies with answer(payload), with this status."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, payload))
            body = json.dumps(answer(payload)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", received
    finally:
        server.shutdown()
        server.server_close()


def v2_answer(payload, held=True):
    """What a v2 server answers: every grasp held, each part 0.4 mm off centre, and its sim settings."""
    rows, cols = len(payload["designs"]), len(payload["offsets"])
    return {
        "held": [[held] * cols for _ in range(rows)],
        "in_hand": [[[0.0, 0.4, 0.0, 1.5, 2.0] if held else None] * cols for _ in range(rows)],
        "held_after_transport": None if payload["transport"] is None else [[held] * cols for _ in range(rows)],
        "sim": {"envs": 64, "device": "cuda:0", "physics_dt": 1 / 60, "friction_combine": "average"},
    }


def test_factory_builds_the_configured_backend():
    mock = create_sim_client(SimConfig())
    assert isinstance(mock, MockSim) and mock.badge == "mock"
    client = create_sim_client(SimConfig(backend="http", url="http://gpu:9000/", timeout_s=5))
    assert (client.url, client.timeout_s, client.badge) == ("http://gpu:9000", 5, "isaac")
    assert client.reconnect_s == 120 * 60  # SIM_RECONNECT_MINUTES


def test_sim_badge_names_what_each_backends_results_are_labelled():
    assert (sim_badge("mock"), sim_badge("http")) == ("mock", "isaac")


# The mock: held


def test_mock_holds_a_centred_part_and_misses_one_beyond_the_slack_and_lead_in():
    finger = build_finger(CAP, Design(params=WIDE_SLACK))

    [outcomes] = MockSim().run_batch(CAP, [finger], [CENTRED, FAR], NO_TRANSPORT)

    assert outcomes.held == [True, False]
    assert outcomes.in_hand[1] is None


def test_mock_stock_fingers_hold_the_cube_but_cannot_open_around_the_cap():
    assert MockSim().run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)[0].held == [True]
    assert MockSim().run_batch(CAP, [None], [CENTRED], NO_TRANSPORT)[0].held == [False]


def test_mock_flat_pads_cannot_square_up_a_box_turned_too_far():
    finger = build_finger(CUBE, Design(params={"pad_width_mm": 10, "slack_mm": 5, "tip_height_mm": 3}))

    [outcomes] = MockSim().run_batch(CUBE, [finger], [at(yaw_deg=10), at(yaw_deg=40)], NO_TRANSPORT)

    assert outcomes.held == [True, False]


def test_mock_checks_a_mesh_part_against_its_own_outline_not_its_bounding_box():
    """Shifted past the slack, the fingertips miss the I's narrow waist; they'd come down on a box its size."""
    params = {"pad_width_mm": 6, "slack_mm": 2, "tip_height_mm": 2}
    box = Part(shape="box", width_mm=20, depth_mm=24, height_mm=10)
    shifted = at(dx=3.0, yaw_deg=5.0)

    [mesh] = MockSim().run_batch(I_BEAM, [build_finger(I_BEAM, Design(params=params))], [shifted], NO_TRANSPORT)
    [boxed] = MockSim().run_batch(box, [build_finger(box, Design(params=params))], [shifted], NO_TRANSPORT)

    assert (mesh.held, boxed.held) == ([True], [False])
    assert mesh.in_hand == [(0.0, 0.0, 0.0, 0.0, 5.0)], "no squaring claim for a mesh: it keeps the offset's yaw"


# The mock: in-hand estimates (geometry only, never predictions)


def test_mock_flat_pads_squeeze_a_part_to_the_centre_along_the_jaws_and_leave_it_where_it_landed_across_them():
    finger = build_finger(CAP, Design(params=FLAT))

    [outcomes] = MockSim().run_batch(CAP, [finger], [at(dx=1.0, dy=2.0), at(dx=-1.0, dy=-5.0)], NO_TRANSPORT)

    assert outcomes.in_hand == [(0.0, 2.0, 0.0, 0.0, 0.0), (0.0, -5.0, 0.0, 0.0, 0.0)]


def test_mock_groove_centres_a_round_part_that_lands_within_its_mouth():
    finger = build_finger(CAP, Design(params=V_GROOVE))
    offsets = [at(dy=dy) for dy in (-2.9, -1.0, 0.0, 2.0, 2.9)]

    [outcomes] = MockSim().run_batch(CAP, [finger], offsets, NO_TRANSPORT)

    assert all(outcomes.held)
    assert [pose[1] for pose in outcomes.in_hand] == pytest.approx([0.0] * len(offsets))


def test_mock_groove_leaves_a_round_part_that_lands_on_its_shoulder():
    finger = build_finger(CAP, Design(params=V_GROOVE))

    [outcomes] = MockSim().run_batch(CAP, [finger], [at(dy=3.5), at(dy=-6.0)], NO_TRANSPORT)

    assert outcomes.held == [True, True]
    assert [pose[1] for pose in outcomes.in_hand] == pytest.approx([3.5, -6.0])


def test_mock_groove_as_wide_as_the_pad_centres_anywhere_on_it():
    finger = build_finger(CAP, Design(params={**FLAT, "groove_angle_deg": 90, "groove_depth_mm": 30}))

    [outcomes] = MockSim().run_batch(CAP, [finger], [at(dy=6.0)], NO_TRANSPORT)

    assert outcomes.in_hand[0][1] == pytest.approx(0.0)


def test_mock_flat_pads_square_up_a_box_and_a_lying_cylinder():
    tube = Part(diameter_mm=10, length_mm=12, axis="x")
    params = {"pad_width_mm": 10, "slack_mm": 5, "tip_height_mm": 3}

    for part in (CUBE, tube):
        [outcomes] = MockSim().run_batch(part, [build_finger(part, Design(params=params))], [at(dy=1.0, yaw_deg=-12.0)], NO_TRANSPORT)
        assert outcomes.in_hand == [(0.0, 1.0, 0.0, 0.0, 0.0)], part.shape


def test_mock_grooved_pads_make_no_squaring_claim_for_a_box():
    finger = build_finger(
        CUBE, Design(params={"pad_width_mm": 10, "slack_mm": 5, "tip_height_mm": 3, "groove_angle_deg": 90, "groove_depth_mm": 2})
    )

    [outcomes] = MockSim().run_batch(CUBE, [finger], [at(dy=1.0, yaw_deg=10.0)], NO_TRANSPORT)

    assert outcomes.in_hand == [(0.0, 1.0, 0.0, 0.0, 10.0)]


def test_mock_stock_fingers_are_flat_pads():
    [outcomes] = MockSim().run_batch(CUBE, [None], [at(dx=0.5, dy=1.0, yaw_deg=8.0)], NO_TRANSPORT)

    assert outcomes.in_hand == [(0.0, 1.0, 0.0, 0.0, 0.0)]


def test_mock_reports_held_after_transport_only_when_the_task_has_a_transport_move():
    finger = build_finger(CAP, Design(params=WIDE_SLACK))

    [still] = MockSim().run_batch(CAP, [finger], [CENTRED, FAR], NO_TRANSPORT)
    [moved] = MockSim().run_batch(CAP, [finger], [CENTRED, FAR], SimSettings(transport="fast"))

    assert still.held_after_transport is None
    assert moved.held_after_transport == moved.held == [True, False]


def test_mock_drops_every_grasp_of_a_finger_that_barely_touches_the_part():
    finger = build_finger(CUBE, Design(params={"pad_width_mm": 10, "slack_mm": 5, "tip_height_mm": 9}))

    [outcomes] = MockSim().run_batch(CUBE, [finger], [CENTRED, CENTRED], SimSettings(transport="slow"))

    assert (outcomes.held, outcomes.in_hand, outcomes.held_after_transport) == ([False, False], [None, None], [False, False])


def test_mock_describes_nothing():
    assert MockSim().describe() == {}


# The sim server client


@pytest.fixture
def sim_server():
    with stand_in(v2_answer) as server:
        yield server


def test_http_client_sends_the_v2_batch_contract(sim_server):
    url, received = sim_server
    part = CAP.model_copy(update={"axis": "y", "friction": (0.4, 0.3), "mass_g": 12.0})
    finger = build_finger(part, Design(params=WIDE_SLACK))

    HttpSim(url, timeout_s=5).run_batch(part, [None, finger], [CENTRED, at(1, -2)], SimSettings(grip_force_n=40.0, transport="normal"))

    [(path, payload)] = received
    assert path == "/evaluate_batch"
    assert payload["part"] == {
        "shape": "cylinder",
        "diameter_mm": 31.75,
        "length_mm": 15.7,
        "axis": "y",
        "mass_g": 12.0,
        "friction": [0.4, 0.3],
    }
    assert payload["designs"][0] == {"id": "stock"}
    design = payload["designs"][1]
    assert set(design) == {"id", "pieces", "friction", "tip_height_mm", "jaw_close_mm"}
    assert design["friction"] == [0.4, 0.3], "the part's pair coefficient goes on the fingers too (D7)"
    assert len(design["pieces"]) == len(finger.pieces) and set(design["pieces"][0]) == {"points", "triangles"}
    assert payload["offsets"] == [CENTRED, {"dx": 1.0, "dy": -2.0, "yaw_deg": 0.0}]
    assert (payload["grip_force_n"], payload["transport"]) == (40.0, "normal")


def test_the_stock_fingers_close_on_a_section_grip_not_the_whole_part(sim_server):
    url, received = sim_server
    # A 12 mm box gripped by a 6 mm section of it: the server's stock rule would close on the 12 mm
    part = Part(shape="box", width_mm=12, depth_mm=30, height_mm=12, grip_width_mm=6, grip_span_mm=(-12.0, 9.0))

    HttpSim(url, timeout_s=5).run_batch(part, [None], [CENTRED], SimSettings())

    [(_, payload)] = received
    assert payload["designs"] == [{"id": "stock", "jaw_close_mm": pytest.approx(0.7)}]  # 6 / 2 - 2 mm hook tip - 0.3 mm squeeze
    assert "grip_width_mm" not in payload["part"]  # the sim gets the whole part


@pytest.mark.parametrize(
    ("part", "fields"),
    [(CUBE, {"box_mm": [10, 10, 10]}), (I_BEAM, {"pieces": [piece.model_dump(mode="json") for piece in I_BEAM.pieces]})],
    ids=["box", "mesh"],
)
def test_http_client_sends_only_the_fields_of_the_parts_shape(sim_server, part, fields):
    url, received = sim_server

    HttpSim(url, timeout_s=5).run_batch(part, [None], [CENTRED], NO_TRANSPORT)

    [(_, payload)] = received
    assert payload["part"] == {"shape": part.shape, **fields, "mass_g": part.mass_g, "friction": list(part.friction)}
    assert (payload["grip_force_n"], payload["transport"]) == (None, None)


def test_http_client_reads_held_in_hand_and_transport_per_design(sim_server):
    url, _ = sim_server

    outcomes = HttpSim(url, timeout_s=5).run_batch(CUBE, [None, None], [CENTRED, FAR, CENTRED], SimSettings(transport="slow"))

    assert len(outcomes) == 2
    for design in outcomes:
        assert design.held == [True, True, True]
        assert design.in_hand == [(0.0, 0.4, 0.0, 1.5, 2.0)] * 3
        assert design.held_after_transport == [True, True, True]


def test_http_client_describes_the_sim_settings_of_its_last_batch(sim_server):
    url, _ = sim_server
    sim = HttpSim(url, timeout_s=5)
    assert sim.describe() == {"url": url.rstrip("/")}

    sim.run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)

    assert sim.describe() == {"envs": 64, "device": "cuda:0", "physics_dt": 1 / 60, "friction_combine": "average", "url": url.rstrip("/")}


def test_http_client_reads_a_server_that_reports_only_held():
    """A v1 server: no in_hand, no held_after_transport, no sim block. Fine without a transport move; with one, the
    missing transport results would score every held grasp as held through transport, so it's an error."""
    with stand_in(lambda payload: {"held": [[1, 0]]}) as (url, _):
        sim = HttpSim(url, timeout_s=5)
        [outcomes] = sim.run_batch(CUBE, [None], [CENTRED, FAR], NO_TRANSPORT)
        with pytest.raises(SimResponseError, match="held_after_transport"):
            sim.run_batch(CUBE, [None], [CENTRED, FAR], SimSettings(transport="fast"))

    assert (outcomes.held, outcomes.in_hand, outcomes.held_after_transport) == ([True, False], [None, None], None)
    assert sim.describe() == {"url": url.rstrip("/")}


def test_http_client_reads_null_in_hand_and_transport_and_drops_poses_of_grasps_that_missed():
    answer = {"held": [[True, False, True]], "in_hand": [[None, [5, 5, 5, 5, 5], [0, 1, 0, 0, 0]]], "held_after_transport": None}
    with stand_in(lambda payload: answer) as (url, _):
        [outcomes] = HttpSim(url, timeout_s=5).run_batch(CUBE, [None], [CENTRED] * 3, NO_TRANSPORT)

    assert outcomes.in_hand == [None, None, (0.0, 1.0, 0.0, 0.0, 0.0)]
    assert outcomes.held_after_transport is None


def test_http_client_reads_the_landing_per_design_and_none_from_an_older_server():
    answer = {"held": [[True, True], [False, True]], "landing": [[[0.25, 1], [3, 0.5]], [None, [0, 12.5]]]}
    with stand_in(lambda payload: answer) as (url, _):
        sim = HttpSim(url, timeout_s=5)
        first, second = sim.run_batch(CUBE, [None, None], [CENTRED, FAR], NO_TRANSPORT)
    with stand_in(lambda payload: {"held": [[True, True]]}) as (url, _):
        [older] = HttpSim(url, timeout_s=5).run_batch(CUBE, [None], [CENTRED, FAR], NO_TRANSPORT)

    assert first.landing == [(0.25, 1.0), (3.0, 0.5)]
    assert second.landing == [None, (0.0, 12.5)]
    assert older.landing is None


def test_http_client_ignores_transport_results_it_did_not_ask_for():
    with stand_in(lambda payload: {"held": [[True]], "held_after_transport": [[False]]}) as (url, _):
        [outcomes] = HttpSim(url, timeout_s=5).run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)

    assert outcomes.held_after_transport is None


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"held": [[1]]}, "held as 1 x 1 for 2 designs x 1 offsets"),
        ({"held": [[1], [1, 1]]}, "held as 2 x 1/2 for 2 designs x 1 offsets"),
        ({"held": [[1], [1]], "in_hand": [[None, None], [None]]}, "in_hand as 2 x 1/2"),
        ({"held": [[1], [1]], "held_after_transport": [[1]]}, "held_after_transport as 1 x 1"),
        ({"held": [[1], [1]], "in_hand": [[[0, 0, 0]], [None]]}, "not \\[dx, dy, dz, tilt, yaw\\]"),
        ({"held": [[1], [1]], "landing": [[[0.5]], [None]]}, "not \\[shift_mm, turn_deg\\]"),
        ({"held": [["yes"], [1]]}, "'yes' in held"),
        ({"in_hand": [[None], [None]]}, "no 'held'"),
    ],
    ids=["too few designs", "too many offsets", "in_hand shape", "transport shape", "short pose", "short landing", "not a flag", "no held"],
)
def test_http_client_rejects_an_answer_that_does_not_match_the_batch(answer, message):
    with stand_in(lambda payload: answer) as (url, _):
        with pytest.raises(SimResponseError, match=message):
            HttpSim(url, timeout_s=5).run_batch(CUBE, [None, None], [CENTRED], SimSettings(transport="slow"))


def test_http_client_passes_on_the_servers_reason_for_refusing_a_batch():
    with stand_in(lambda payload: {"detail": "no IK solution for the grasp at (0.30, 0.00)"}, status=422) as (url, _):
        with pytest.raises(SimError, match="answered 422: no IK solution"):
            HttpSim(url, timeout_s=5).run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (urllib.error.URLError(ConnectionRefusedError("refused")), "can't reach the sim server"),
        (ConnectionResetError("reset by peer"), "lost the connection to the sim server at http://gpu:9000: reset by peer"),
        (TimeoutError(), "didn't answer within 5 s"),
    ],
    ids=["refused", "reset", "timeout"],
)
def test_http_client_says_when_the_server_cannot_be_reached(monkeypatch, failure, message):
    def fail(request, timeout):
        raise failure

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    with pytest.raises(SimError, match=message):
        HttpSim("http://gpu:9000", timeout_s=5).run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)


# The sim server client after a lost connection


class Clock:
    """A clock that sleeping moves forward, so waits take no real time."""

    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@contextmanager
def dropping_stand_in(answer, *, drops=1, down_checks=0, fail_with=None):
    """A sim server behind a port forward that goes down: the first `drops` batches are cut off before their answer
    (fail_with None) or refused with that status, and after the first, /health fails `down_checks` times before it
    answers again. Records each batch's Idempotency-Key."""
    keys, left = [], {"drops": drops, "down": down_checks}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            keys.append(self.headers["Idempotency-Key"])
            if not left["drops"]:
                self.reply(200, answer(payload))
            elif fail_with is None:
                left["drops"] -= 1
                self.close_connection = True  # no answer: the client sees the connection end
            else:
                left["drops"] -= 1
                self.reply(fail_with, {"detail": "the sim server is shutting down"})

        def do_GET(self):
            if keys and left["down"]:
                left["down"] -= 1
                self.reply(503, {"detail": "down"})
            else:
                self.reply(200, {"status": "ok"})

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", keys
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("fail_with", [None, 503], ids=["cut off", "server restarting"])
def test_a_batch_whose_connection_is_lost_is_sent_again_under_its_key_once_the_server_answers(fail_with):
    clock = Clock()
    with dropping_stand_in(v2_answer, drops=1, down_checks=2, fail_with=fail_with) as (url, keys):
        sim = HttpSim(url, timeout_s=5, reconnect_s=600, sleep=clock.sleep, clock=clock)
        [outcomes] = sim.run_batch(CUBE, [None], [CENTRED, FAR], NO_TRANSPORT)

    assert outcomes.held == [True, True]
    assert len(keys) == 2 and keys[0] == keys[1], "the same key, so the server answers from the batch it already ran"
    assert clock.sleeps == [10.0, 10.0, 10.0]  # /health down twice, then answering


def test_each_batch_gets_its_own_key():
    with dropping_stand_in(v2_answer, drops=0) as (url, keys):
        sim = HttpSim(url, timeout_s=5, reconnect_s=600)
        sim.run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)
        sim.run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)

    assert len(set(keys)) == 2


def test_a_lost_connection_that_does_not_come_back_fails_the_round_with_how_to_carry_on():
    clock = Clock()
    with dropping_stand_in(v2_answer, drops=1, down_checks=1000) as (url, keys):
        sim = HttpSim(url, timeout_s=5, reconnect_s=60, sleep=clock.sleep, clock=clock)
        with pytest.raises(SimError, match="didn't answer again within 1 min: reconnect the GPU in the GPU panel, then resume"):
            sim.run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)

    assert len(keys) == 1 and clock.sleeps == [10.0] * 6


def test_a_server_that_never_answered_is_not_waited_for(monkeypatch):
    """Nothing answered yet: a wrong SIM_URL, or the GPU isn't connected. The job fails at once with the reason."""
    clock = Clock()

    def refuse(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    sim = HttpSim("http://gpu:9000", timeout_s=5, reconnect_s=600, sleep=clock.sleep, clock=clock)

    with pytest.raises(SimError, match="can't reach the sim server at http://gpu:9000: refused"):
        sim.run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)
    assert clock.sleeps == []


def test_a_batch_the_server_refuses_is_not_sent_again():
    clock = Clock()
    with dropping_stand_in(v2_answer, drops=1, fail_with=422) as (url, keys):
        sim = HttpSim(url, timeout_s=5, reconnect_s=600, sleep=clock.sleep, clock=clock)
        with pytest.raises(SimError, match="answered 422"):
            sim.run_batch(CUBE, [None], [CENTRED], NO_TRANSPORT)

    assert len(keys) == 1 and clock.sleeps == []


# Recording one grasp (the app's clips)


def recording_answer(payload):
    """What the sim server answers to POST /record_grasp: the grasp's outcome and a "video" per view asked for."""
    videos = {view: base64.b64encode(f"{view} mp4".encode()).decode() for view in payload["views"]}
    outcome = {"held": True, "in_hand": [0.0, 0.4, 0.0, 1.5, 2.0], "held_after_transport": None}
    return outcome | {"fps": 30, "frames": 147, "duration_s": 4.9, "videos": videos, "sim": {"envs": 1, "device": "cpu"}}


def test_http_client_asks_the_sim_server_to_film_one_grasp():
    with stand_in(recording_answer) as (url, received):
        recording = HttpSim(url, timeout_s=5).record(CUBE, None, at(1, -2), SimSettings(grip_force_n=12.0), ["closeup", "side"])

    [(path, payload)] = received
    assert path == "/record_grasp" and payload["design"] == {"id": "stock"} and payload["part"]["shape"] == "box"
    assert payload["offset"] == {"dx": 1.0, "dy": -2.0, "yaw_deg": 0.0} and payload["views"] == ["closeup", "side"]
    assert (payload["grip_force_n"], payload["transport"]) == (12.0, None)
    assert recording.held and recording.in_hand == (0.0, 0.4, 0.0, 1.5, 2.0) and (recording.frames, recording.duration_s) == (147, 4.9)
    assert recording.videos == {"closeup": b"closeup mp4", "side": b"side mp4"}


@pytest.mark.parametrize(
    ("answer", "message"),
    [({"held": True, "videos": {}}, "without videos"), ({"held": True, "videos": {"closeup": "not base64!"}}, "can't be read")],
    ids=["no videos", "not base64"],
)
def test_http_client_rejects_a_recording_it_cant_use(answer, message):
    with stand_in(lambda payload: answer) as (url, _):
        with pytest.raises(SimResponseError, match=message):
            HttpSim(url, timeout_s=5).record(CUBE, None, CENTRED, NO_TRANSPORT, ["closeup"])


def test_the_mock_cant_film_a_grasp():
    with pytest.raises(SimError, match="clips need the Isaac sim"):
        MockSim().record(CUBE, None, CENTRED, NO_TRANSPORT, ["closeup"])


@pytest.mark.parametrize("client", [MockSim(), HttpSim("http://gpu:9000", timeout_s=5, reconnect_s=600)])
def test_clients_survive_pickling(client):
    copy = pickle.loads(pickle.dumps(client))

    assert (copy.backend, copy.badge, copy.url) == (client.backend, client.badge, client.url)
