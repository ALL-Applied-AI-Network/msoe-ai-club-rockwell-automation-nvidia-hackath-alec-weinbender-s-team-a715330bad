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
from sim_server.models.outcome import BatchOutcome
from sim_server.models.pose import InHandPose
from sim_server.routers import evaluations
from sim_server.routers.evaluations import EvaluateBatchRequest, to_batch
from sim_server.sim_queue import SimQueue

BATCHES = Path(__file__).resolve().parents[2] / "scripts" / "batches"
CUBE = {"shape": "box", "box_mm": [10, 10, 10], "mass_g": 4}
OFFSETS = [{"dx": 0, "dy": 0, "yaw_deg": 0}, {"dx": 1.5, "dy": -2, "yaw_deg": 10}]
# The keys the backend compares with its cell profile (api/models/cell_profile.SERVER_SIM_KEYS), plus an extra.
DESCRIPTION = {
    "envs": 1,
    "device": "cpu",
    "friction_combine": "average",
    "physics_dt": 1 / 60,
    "solver_position_iterations": 16,
    "solver_velocity_iterations": 2,
    "contact_offset_mm": 0.2,
    "rest_offset_mm": 0.0,
    "solver_type": "TGS",
}


class FakeScene:
    cell = "the cell"

    def describe(self) -> dict:
        return dict(DESCRIPTION)


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
    """Replaces evaluate_batch; records (cell, batch) and answers a checkerboard of held flags, with an in-hand pose of
    (offset index mm, -0.5 mm, 0.1 mm, 1 deg, 2 deg) wherever it held."""
    calls: list[tuple[object, GraspBatch]] = []
    error: list[Exception] = []

    def fake(cell, batch: GraspBatch) -> BatchOutcome:
        if error:
            raise error[0]
        calls.append((cell, batch))
        held = [[(d + o) % 2 == 0 for o in range(len(batch.offsets))] for d in range(len(batch.designs))]
        in_hand = [
            [InHandPose(dx=o * 1e-3, dy=-5e-4, dz=1e-4, tilt_deg=1.0, yaw_deg=2.0) if ok else None for o, ok in enumerate(row)]
            for row in held
        ]
        return BatchOutcome(
            held=tuple(map(tuple, held)),
            in_hand=tuple(map(tuple, in_hand)),
            held_after_transport=None if batch.transport is None else tuple(tuple(False for _ in row) for row in held),
        )

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
    assert response.json() == {
        "held": [[True, False], [False, True]],
        "in_hand": [[[0.0, -0.5, 0.1, 1.0, 2.0], None], [None, [1.0, -0.5, 0.1, 1.0, 2.0]]],
        "held_after_transport": None,  # no transport asked for
        "sim": DESCRIPTION,
    }
    ((cell, batch),) = service.calls
    assert cell == "the cell"  # the job runs on the scene's cell
    assert batch.part.size == pytest.approx((0.01, 0.01, 0.01)) and batch.part.mass == pytest.approx(0.004)
    assert batch.part.friction is None and batch.grip_force is None and batch.transport is None
    stock, custom = batch.designs
    assert stock.is_stock and custom.pieces[0].points[-1] == pytest.approx((0.012, 0.003, 0.076))
    assert custom.tip_height == pytest.approx(0.004) and custom.jaw_close == pytest.approx(0.0012)
    assert batch.offsets[1].dx == pytest.approx(0.0015) and batch.offsets[1].dy == pytest.approx(-0.002)
    assert batch.offsets[1].yaw_deg == 10


def test_grip_force_and_transport_reach_the_batch(service):
    body = {"part": CUBE, "designs": [{"id": "stock"}], "offsets": OFFSETS, "grip_force_n": 12.5, "transport": "slow"}
    response = client().post("/evaluate_batch", json=body)
    assert response.status_code == 200 and response.json()["held_after_transport"] == [[False, False]]
    ((_, batch),) = service.calls
    assert batch.grip_force == 12.5 and batch.transport == "slow"


def test_the_backends_v2_payload_is_accepted(service, box_piece):
    """What app/backend's HttpSim sends (clients/sim.py): every part field whatever the shape, axis instead of upright,
    the part's friction, the same pair on each custom design, and the top-level grip force and transport."""
    leg, foot = box_piece(-5, 5, -2, 2, 0, 24), box_piece(-5, 5, -18, -2, 0, 4)
    part = {
        "shape": "mesh",
        "diameter_mm": 31.75,
        "length_mm": 15.7,
        "axis": "z",
        "box_mm": [10, 10, 10],
        "mass_g": 4.3,
        "friction": [0.45, 0.35],
        "pieces": [{"points": p, "triangles": t} for p, t in (leg, foot)],
    }
    designs = [{"id": "stock"}, custom_design(box_piece, id="d1", friction=[0.45, 0.35])]
    body = {"part": part, "designs": designs, "offsets": OFFSETS, "grip_force_n": None, "transport": "fast"}
    response = client().post("/evaluate_batch", json=body)
    assert response.status_code == 200, response.text
    ((_, batch),) = service.calls
    assert batch.part.shape == "mesh" and batch.part.size == pytest.approx((0.010, 0.020, 0.024))
    assert batch.part.friction == (0.45, 0.35) and batch.designs[1].friction == (0.45, 0.35)
    assert batch.grip_force is None and batch.transport == "fast"
    cylinder = part | {"shape": "cylinder", "axis": "x", "diameter_mm": 10, "length_mm": 20}
    assert client().post("/evaluate_batch", json=body | {"part": cylinder}).status_code == 200
    assert service.calls[-1][1].part.size == pytest.approx((0.020, 0.010, 0.010))


def test_the_legacy_upright_flag_still_works(service):
    lying = {"shape": "cylinder", "diameter_mm": 10, "length_mm": 20, "upright": False, "mass_g": 3}
    assert client().post("/evaluate_batch", json={"part": lying, "designs": [{"id": "stock"}], "offsets": OFFSETS}).status_code == 200
    assert service.calls[-1][1].part.cylinder_axis == "y"


@pytest.mark.parametrize(
    "change",
    [
        {"designs": [{"id": "stock", "friction": [0.5, 0.4]}]},  # stock keeps the twin's materials
        {"designs": []},
        {"part": {"shape": "cylinder", "diameter_mm": 10, "mass_g": 3}},  # no length
        {"part": {"shape": "cylinder", "diameter_mm": 10, "length_mm": 20, "axis": "w", "mass_g": 3}},
        {"part": {"shape": "sphere", "diameter_mm": 10, "mass_g": 3}},
        {"part": {"shape": "mesh", "mass_g": 3}},  # no pieces
        {"part": {"shape": "mesh", "pieces": [], "mass_g": 3}},
        {"part": CUBE | {"friction": [0.5]}},
        {"part": CUBE | {"friction": [-0.1, 0.4]}},
        {"offsets": [{"dx": 0, "dy": 0}]},
        {"designs": [{"id": "x", "jaw_close_mm": 7}]},  # beyond the 6 mm stroke
        {"grip_force_n": 0},
        {"grip_force_n": -5},
        {"transport": "warp"},
    ],
)
def test_bad_requests_get_422(service, change):
    body = {"part": CUBE, "designs": [{"id": "stock"}], "offsets": OFFSETS} | change
    assert client().post("/evaluate_batch", json=body).status_code == 422
    assert service.calls == []


def test_a_mesh_part_below_the_table_gets_422(service, box_piece):
    points, triangles = box_piece(-5, 5, -5, 5, -2, 10)
    part = {"shape": "mesh", "pieces": [{"points": points, "triangles": triangles}], "mass_g": 3}
    response = client().post("/evaluate_batch", json={"part": part, "designs": [{"id": "stock"}], "offsets": OFFSETS})
    assert response.status_code == 422 and "below the table" in response.json()["detail"]


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
    assert response.status_code == 200 and response.json() == {"successes": [True, False]}  # held only
    assert service.calls[0][1].designs[0].is_stock


def test_legacy_evaluate_refuses_templates_it_cant_build(service):
    body = {"part": CUBE, "design": {"template": "flat_pad", "params": {"pad_width": 10}}, "offsets": OFFSETS}
    response = client().post("/evaluate", json=body)
    assert response.status_code == 501 and "/evaluate_batch" in response.json()["detail"]
    assert service.calls == []


@pytest.mark.parametrize("path", sorted(BATCHES.glob("*.json")), ids=lambda p: p.name)
def test_example_batches_are_valid_requests(path):
    request = EvaluateBatchRequest.model_validate(json.loads(path.read_text()))
    batch = to_batch(request.part, request.designs, request.offsets, request.grip_force_n, request.transport)
    assert batch.designs and batch.offsets


def test_the_new_example_batches_exercise_contract_v2():
    def load(name):
        request = EvaluateBatchRequest.model_validate(json.loads((BATCHES / name).read_text()))
        return to_batch(request.part, request.designs, request.offsets, request.grip_force_n, request.transport)

    bracket = load("mesh_l_bracket.json")
    assert bracket.part.shape == "mesh" and len(bracket.part.pieces) == 2 and bracket.part.friction == (0.45, 0.35)
    assert load("stock_cube_transport.json").transport == "normal"
    heavy = load("heavy_block_grip_force.json")
    assert heavy.grip_force == 15 and heavy.part.mass == pytest.approx(0.3)
