"""routers/health.py: answers from the queue and the scene's description, never touching Isaac."""

from fastapi.testclient import TestClient

from sim_server.app import create_app


class FakeScene:
    def describe(self) -> dict:
        return {"envs": 64, "device": "cuda:0", "friction_combine": "max"}


class FakeQueue:
    queued = 3


def test_health_reports_the_queue_and_the_path():
    response = TestClient(create_app(FakeScene(), FakeQueue())).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "queued": 3, "envs": 64, "device": "cuda:0", "friction_combine": "max"}
