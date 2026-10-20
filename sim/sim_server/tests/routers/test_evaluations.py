"""routers/evaluations.py: validation, unit conversion at the boundary, response shape and error codes. No Isaac and no
business logic: the service (services/evaluations.evaluate_batch) is replaced by a fake, and an immediate queue runs jobs on
the spot (the real SimQueue needs the main thread, which TestClient blocks)."""

import json
from concurrent.futures import Future
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sim_server.app import create_app
from sim_server.models.batch import GraspBatch
from sim_server.models.grasp import GraspPlanError
from sim_server.routers import evaluations
from sim_server.routers.evaluations import EvaluateBatchRequest, to_batch
from sim_server.sim_queue import SimQueue

BATCHES = Path(__file__).resolve().parents[2] / "scripts" / "batches"
CUBE = {"shape": "box", "box_mm": [10, 10, 10], "mass_g": 4}
OFFSETS = [{"dx": 0, "dy": 0, "yaw_deg": 0}, {"dx": 1.5, "dy": -2, "yaw_deg": 10}]


class FakeScene:
    cell = "the cell"

    def describe(self) -> dict:
        return {"envs": 1, "device": "cpu", "friction_combine": "average"}


class ImmediateQueue:
    queued = 0

    def submit(self, fn, /, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as e:
            future.set_exception(e)
        return future


@pytest.fixture
def service(monkeypatch):
    """Replaces evaluate_batch; records (cell, batch) and answers a checkerboard of held flags."""
    calls: list[tuple[object, GraspBatch]] = []
    error: list[Exception] = []

    def fake(cell, batch: GraspBatch) -> list[list[bool]]:
        if error:
            raise error[0]
        calls.append((cell, batch))
        return [[(d + o) % 2 == 0 for o in range(len(batch.offsets))] for d in range(len(batch.designs))]

    monkeypatch.setattr(evaluations, "evaluate_batch", fake)
    fake.calls, fake.error = calls, error
    return fake


def client(queue=None) -> TestClient:
    return TestClient(create_app(FakeScene(), queue or ImmediateQueue()))


def custom_design(box_piece, **overrides) -> dict:
    points, triangles = box_piece(0, 12, -3, 3, 0, 76)
    design = {"id": "t3", "pieces": [{"points": points, "triangles": triangles}], "friction": [0.6, 0.5]}
    return design | {"tip_height_mm": 4.0, "jaw_close_mm": 1.2} | overrides


def test_batch_converts_units_and_answers_one_row_per_design(service, box_piece):
    body = {"part": CUBE, "designs": [{"id": "stock"}, custom_design(box_piece)], "offsets": OFFSETS}
    response = client().post("/evaluate_batch", json=body)
    assert response.status_code == 200
    assert response.json() == {"held": [[True, False], [False, True]]}
    ((cell, batch),) = service.calls
    assert cell == "the cell"  # the job runs on the scene's cell
    assert batch.part.size == pytest.approx((0.01, 0.01, 0.01)) and batch.part.mass == pytest.approx(0.004)
    stock, custom = batch.designs
    assert stock.is_stock and custom.pieces[0].points[-1] == pytest.approx((0.012, 0.003, 0.076))
    assert custom.tip_height == pytest.approx(0.004) and custom.jaw_close == pytest.approx(0.0012)
    assert batch.offsets[1].dx == pytest.approx(0.0015) and batch.offsets[1].dy == pytest.approx(-0.002)
    assert batch.offsets[1].yaw_deg == 10


@pytest.mark.parametrize(
    "change",
    [
        {"designs": [{"id": "stock", "friction": [0.5, 0.4]}]},  # stock keeps the twin's materials
        {"designs": []},
        {"part": {"shape": "cylinder", "diameter_mm": 10, "mass_g": 3}},  # no length
        {"part": {"shape": "sphere", "diameter_mm": 10, "mass_g": 3}},
        {"offsets": [{"dx": 0, "dy": 0}]},
        {"designs": [{"id": "x", "jaw_close_mm": 7}]},  # beyond the 6 mm stroke
    ],
)
def test_bad_requests_get_422(service, change):
    body = {"part": CUBE, "designs": [{"id": "stock"}], "offsets": OFFSETS} | change
    assert client().post("/evaluate_batch", json=body).status_code == 422
    assert service.calls == []


def test_custom_design_needs_its_grasp_settings(service, box_piece):
    design = custom_design(box_piece)
    del design["jaw_close_mm"]
    response = client().post("/evaluate_batch", json={"part": CUBE, "designs": [design], "offsets": OFFSETS})
    assert response.status_code == 422 and "jaw_close_mm" in response.json()["detail"]


def test_bad_triangle_index_gets_422(service, box_piece):
    design = custom_design(box_piece)
    design["pieces"][0]["triangles"].append([0, 1, 99])
    assert client().post("/evaluate_batch", json={"part": CUBE, "designs": [design], "offsets": OFFSETS}).status_code == 422


def test_unplannable_grasp_gets_422(service):
    service.error.append(GraspPlanError("IK failed during descend"))
    response = client().post("/evaluate_batch", json={"part": CUBE, "designs": [{"id": "stock"}], "offsets": OFFSETS})
    assert response.status_code == 422 and "IK failed" in response.json()["detail"]


def test_shutting_down_gets_503(service):
    queue = SimQueue()
    queue.close()
    response = client(queue).post("/evaluate_batch", json={"part": CUBE, "designs": [{"id": "stock"}], "offsets": OFFSETS})
    assert response.status_code == 503


def test_legacy_evaluate_runs_stock_through_the_batch_path(service):
    body = {"part": CUBE, "design": {"template": "stock", "params": {}}, "offsets": OFFSETS}
    response = client().post("/evaluate", json=body)
    assert response.status_code == 200 and response.json() == {"successes": [True, False]}
    assert service.calls[0][1].designs[0].is_stock


def test_legacy_evaluate_refuses_templates_it_cant_build(service):
    body = {"part": CUBE, "design": {"template": "flat_pad", "params": {"pad_width": 10}}, "offsets": OFFSETS}
    response = client().post("/evaluate", json=body)
    assert response.status_code == 501 and "/evaluate_batch" in response.json()["detail"]
    assert service.calls == []


@pytest.mark.parametrize("path", sorted(BATCHES.glob("*.json")), ids=lambda p: p.name)
def test_example_batches_are_valid_requests(path):
    request = EvaluateBatchRequest.model_validate(json.loads(path.read_text()))
    batch = to_batch(request.part, request.designs, request.offsets)
    assert batch.designs and batch.offsets
