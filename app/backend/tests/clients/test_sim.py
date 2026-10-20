import json
import pickle
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from api.clients.sim import HttpSim, MockSim, create_sim_client
from api.config import SimConfig
from api.models.design import Design
from api.models.finger import build_finger
from api.models.part import Part

CAP, CUBE = Part(), Part(shape="box")
WIDE_SLACK = {"pad_width_mm": 30, "groove_angle_deg": 180, "groove_depth_mm": 0, "slack_mm": 5, "tip_height_mm": 3, "lead_in_mm": 2}
CENTRED, FAR = {"dx": 0.0, "dy": 0.0, "yaw_deg": 0.0}, {"dx": 9.0, "dy": 0.0, "yaw_deg": 0.0}


@contextmanager
def stand_in(answer):
    """A stand-in for sim/sim_server: records each request and replies with answer(payload)."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, payload))
            body = json.dumps(answer(payload)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/", received
    server.shutdown()


@pytest.fixture
def sim_server():
    """Answers 'held' for every design at every offset."""
    with stand_in(lambda payload: {"held": [[1] * len(payload["offsets"]) for _ in payload["designs"]]}) as server:
        yield server


def test_factory_builds_the_configured_backend():
    assert isinstance(create_sim_client(SimConfig()), MockSim)
    client = create_sim_client(SimConfig(backend="http", url="http://gpu:9000/", timeout_s=5))
    assert (client.url, client.timeout_s) == ("http://gpu:9000", 5)


def test_mock_holds_a_centred_part_and_misses_one_beyond_the_slack_and_lead_in():
    finger = build_finger(CAP, Design(params=WIDE_SLACK))

    assert MockSim().run_batch(CAP, [finger], [CENTRED, FAR]) == [[True, False]]


def test_mock_stock_fingers_hold_the_cube_but_cannot_open_around_the_cap():
    assert MockSim().run_batch(CUBE, [None], [CENTRED]) == [[True]]
    assert MockSim().run_batch(CAP, [None], [CENTRED]) == [[False]]


def test_mock_flat_pads_cannot_square_up_a_box_turned_too_far():
    finger = build_finger(CUBE, Design(params={"pad_width_mm": 10, "slack_mm": 5, "tip_height_mm": 3, "lead_in_mm": 0}))

    [row] = MockSim().run_batch(CUBE, [finger], [{"dx": 0, "dy": 0, "yaw_deg": 10}, {"dx": 0, "dy": 0, "yaw_deg": 40}])

    assert row == [True, False]


def test_http_client_sends_the_batch_contract_and_reads_one_row_per_design(sim_server):
    url, received = sim_server
    finger = build_finger(CAP, Design(params=WIDE_SLACK))

    held = HttpSim(url, timeout_s=5).run_batch(CAP, [None, finger], [CENTRED, FAR])

    assert held == [[True, True], [True, True]]
    [(path, payload)] = received
    assert path == "/evaluate_batch"
    assert payload["part"]["box_mm"] == [CAP.width_mm, CAP.depth_mm, CAP.height_mm]
    assert payload["designs"][0] == {"id": "stock"}
    design = payload["designs"][1]
    assert set(design) == {"id", "pieces", "friction", "tip_height_mm", "jaw_close_mm"}
    assert len(design["pieces"]) == len(finger.pieces) and set(design["pieces"][0]) == {"points", "triangles"}
    assert payload["offsets"] == [CENTRED, FAR]


def test_http_client_rejects_an_answer_that_does_not_match_the_batch():
    with stand_in(lambda payload: {"held": [[1]]}) as (url, _):
        with pytest.raises(ValueError, match="2 designs x 1 offsets"):
            HttpSim(url, timeout_s=5).run_batch(CAP, [None, None], [CENTRED])


@pytest.mark.parametrize("client", [MockSim(), HttpSim("http://gpu:9000", timeout_s=5)])
def test_clients_survive_pickling(client):
    copy = pickle.loads(pickle.dumps(client))

    assert (copy.backend, copy.url) == (client.backend, client.url)
