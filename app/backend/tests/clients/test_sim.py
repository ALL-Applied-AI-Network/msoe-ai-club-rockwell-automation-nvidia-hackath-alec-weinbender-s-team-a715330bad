import json
import pickle
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from api.clients.sim import HttpSim, MockSim, create_sim_client
from api.config import SimConfig
from api.models.design import Design
from api.models.part import Part

DESIGN = Design(template="v_groove", params={"finger_length": 40, "groove_angle": 95, "groove_depth": 8, "pad_width": 20})
OFFSETS = [{"dx": 0.5, "dy": -1.0, "yaw_deg": 2.0}, {"dx": 3.0, "dy": 0.0, "yaw_deg": -8.0}]


@pytest.fixture
def sim_server():
    """A stand-in for sim/sim_server that records each request and answers 'held' for every offset."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload)
            body = json.dumps({"successes": [1] * len(payload["offsets"])}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/evaluate", received
    server.shutdown()


def test_factory_builds_the_configured_backend():
    assert isinstance(create_sim_client(SimConfig()), MockSim)
    client = create_sim_client(SimConfig(backend="http", url="http://gpu:9000/evaluate", timeout_s=5))
    assert (client.url, client.timeout_s) == ("http://gpu:9000/evaluate", 5)


def test_mock_returns_one_result_per_offset():
    results = MockSim().run_grasps(Part(), DESIGN, OFFSETS)

    assert len(results) == len(OFFSETS)
    assert all(isinstance(r, bool) for r in results)


def test_http_client_sends_the_sim_server_contract_in_millimetres(sim_server):
    url, received = sim_server

    results = HttpSim(url, timeout_s=5).run_grasps(Part(diameter_mm=12), DESIGN, OFFSETS)

    assert results == [True, True]
    assert received == [{"part": Part(diameter_mm=12).model_dump(), "design": DESIGN.model_dump(), "offsets": OFFSETS}]


@pytest.mark.parametrize("client", [MockSim(), HttpSim("http://gpu:9000/evaluate", timeout_s=5)])
def test_clients_survive_pickling_for_the_optimizer_pool(client):
    copy = pickle.loads(pickle.dumps(client))

    assert (copy.backend, copy.url) == (client.backend, client.url)
