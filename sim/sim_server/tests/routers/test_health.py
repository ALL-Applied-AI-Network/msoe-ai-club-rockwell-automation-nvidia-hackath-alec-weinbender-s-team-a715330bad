"""routers/health.py: answers from the queue and the scene's description, never touching Isaac."""

from fastapi.testclient import TestClient

from sim_server.app import create_app


class FakeScene:
    def describe(self) -> dict:
        return {
            "envs": 64,
            "device": "cuda:0",
            "friction_combine": "max",
            "physics_dt": 1 / 60,
            "solver_position_iterations": 16,
            "solver_velocity_iterations": 2,
            "contact_offset_mm": 0.2,
            "rest_offset_mm": 0.0,
            "robot_solver_iterations": {"position": 32, "velocity": 1},
        }


class FakeQueue:
    queued = 3


def test_health_reports_the_queue_and_everything_the_scene_describes():
    response = TestClient(create_app(FakeScene(), FakeQueue())).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "queued": 3, **FakeScene().describe()}
