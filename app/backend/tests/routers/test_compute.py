"""The GPU panel's API: status, every enabled target's instances, start, stop, sessions, and the providers' errors."""

from api.clients.compute import ComputeError, MockCompute
from api.dependencies import get_compute
from api.main import app
from api.models.compute import ComputeInstance


class GB10(MockCompute):
    """Stands in for the GB10 client: one always-on target."""

    backend = "gb10"
    always_on = True

    def instances(self):
        return [
            ComputeInstance(backend="gb10", name="spark1", id="spark1.ai.msoe.edu", status="AVAILABLE", state="running", always_on=True)
        ]


class Unreachable(MockCompute):
    backend = "gb10"
    always_on = True

    def instances(self):
        raise ComputeError("can't reach the GB10 (spark1.ai.msoe.edu): connect the MSOE VPN (GlobalProtect)")


def use(clients: dict) -> None:
    app.dependency_overrides[get_compute] = lambda: clients


def test_status_with_the_mock_says_jobs_dont_wait(client):
    response = client.get("/api/compute")

    assert response.status_code == 200
    assert response.json() == {
        "backends": [{"name": "mock", "label": "Mock", "always_on": False}],
        "managed": False,
        "auto_stop_minutes": 20,
        "session": None,
        "last": None,
        "not_ready_reason": None,
    }


def test_status_lists_each_enabled_target_and_whether_it_is_always_on(client, config, compute_client):
    use({"mock": compute_client, "gb10": GB10(config.data_dir / "g.json")})

    backends = client.get("/api/compute").json()["backends"]

    assert backends == [{"name": "mock", "label": "Mock", "always_on": False}, {"name": "gb10", "label": "MSOE GB10", "always_on": True}]


def test_instances_come_from_every_backend_tagged_with_it(client, config, compute_client):
    use({"mock": compute_client, "gb10": GB10(config.data_dir / "g.json")})

    body = client.get("/api/compute/instances").json()

    assert [(i["backend"], i["name"], i["state"], i["always_on"]) for i in body["instances"]] == [
        ("mock", "mock-rtx-pro-4500", "stopped", False),
        ("mock", "mock-l40s", "stopped", False),
        ("gb10", "spark1", "running", True),
    ]
    assert body["errors"] == []


def test_a_backend_that_cant_be_reached_doesnt_hide_the_others(client, config, compute_client):
    use({"mock": compute_client, "gb10": Unreachable(config.data_dir / "u.json")})

    body = client.get("/api/compute/instances").json()

    assert [i["backend"] for i in body["instances"]] == ["mock", "mock"]
    assert body["errors"] == [
        {"backend": "gb10", "message": "can't reach the GB10 (spark1.ai.msoe.edu): connect the MSOE VPN (GlobalProtect)"}
    ]


def test_start_answers_202_with_the_starting_session(client, spawned_sessions):
    response = client.post("/api/compute/start", json={"backend": "mock", "instance": "mock-l40s"})

    assert response.status_code == 202
    session = response.json()
    assert (session["backend"], session["instance"], session["status"]) == ("mock", "mock-l40s", "starting")
    assert spawned_sessions == [session["id"]]
    status = client.get("/api/compute").json()
    assert status["session"]["id"] == status["last"]["id"] == session["id"]


def test_connecting_the_gb10_starts_a_session_on_it(client, config, compute_client, spawned_sessions):
    use({"mock": compute_client, "gb10": GB10(config.data_dir / "g.json")})

    response = client.post("/api/compute/start", json={"backend": "gb10", "instance": "spark1"})

    assert response.status_code == 202 and response.json()["backend"] == "gb10"


def test_a_backend_that_isnt_enabled_is_422(client):
    response = client.post("/api/compute/start", json={"backend": "gb10", "instance": "spark1"})

    assert response.status_code == 422
    assert "COMPUTE_BACKENDS doesn't include gb10" in response.json()["detail"]


def test_a_second_target_is_refused_while_one_is_active(client):
    client.post("/api/compute/start", json={"backend": "mock", "instance": "mock-l40s"})

    response = client.post("/api/compute/start", json={"backend": "mock", "instance": "mock-rtx-pro-4500"})

    assert response.status_code == 409
    assert "stop it before starting another target" in response.json()["detail"]


def test_an_unknown_target_is_404(client):
    response = client.post("/api/compute/start", json={"backend": "mock", "instance": "rtx-9090"})

    assert response.status_code == 404


def test_stop_flags_the_session(client):
    client.post("/api/compute/start", json={"backend": "mock", "instance": "mock-l40s"})

    response = client.post("/api/compute/stop")

    assert response.status_code == 202
    assert response.json()["stop_requested"] == 1
    assert client.get("/api/compute/sessions").json()[0]["message"] == "Stopping"


def test_stop_with_nothing_running_is_409(client):
    assert client.post("/api/compute/stop").status_code == 409


def test_a_provider_failure_while_starting_is_502(client, config):
    use({"gb10": Unreachable(config.data_dir / "u.json")})

    response = client.post("/api/compute/start", json={"backend": "gb10", "instance": "spark1"})

    assert response.status_code == 502 and "connect the MSOE VPN" in response.json()["detail"]
