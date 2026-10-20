"""The GPU the sim runs on (the GPU panel): the targets every enabled backend offers, the current session, start and
stop. Brev instances are created in the Brev console and started and stopped here; the MSOE GB10 is always on, so it's
connected and disconnected instead. Starting is asynchronous: 202 with the session, then poll GET /api/compute until it's
ready. One target is connected at a time."""

from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api.clients.compute import ComputeError
from api.dependencies import ComputeDep, ConfigDep, DbDep
from api.models.compute import BACKEND_LABELS, ComputeBackend, ComputeInstance, ComputeSession
from api.services import compute

router = APIRouter(prefix="/api/compute", tags=["compute"])


class BackendInfo(BaseModel):
    name: ComputeBackend
    label: str  # "Brev", "MSOE GB10", "Mock"
    always_on: bool  # true: connect / disconnect (nothing to start or stop, no auto-stop); false: start / stop


class ComputeStatusResponse(BaseModel):
    backends: list[BackendInfo]  # the enabled targets' backends (COMPUTE_BACKENDS)
    managed: bool  # a real target is enabled, so jobs and predictions wait for a ready session
    auto_stop_minutes: float  # Brev only; 0: never
    session: ComputeSession | None  # the one starting, ready or stopping
    last: ComputeSession | None  # the latest session, ended ones included (shows why it stopped or failed)
    not_ready_reason: str | None  # why sim work can't start now; None when it can


class BackendError(BaseModel):
    backend: ComputeBackend
    message: str  # e.g. "can't reach the GB10 (...): connect the MSOE VPN (GlobalProtect)"


class InstancesResponse(BaseModel):
    instances: list[ComputeInstance]  # every enabled backend's targets, each tagged with its backend
    errors: list[BackendError]  # backends that couldn't be asked this time; the others are still listed


class StartSessionRequest(BaseModel):
    backend: ComputeBackend
    instance: str = Field(min_length=1)  # a target's name, from GET /api/compute/instances


@router.get("")
def get_compute(db: DbDep, config: ConfigDep, clients: ComputeDep) -> ComputeStatusResponse:
    """Cheap (no provider call): poll it while a session starts or stops."""
    latest = compute.list_sessions(db, limit=1)
    return ComputeStatusResponse(
        backends=[BackendInfo(name=name, label=BACKEND_LABELS[name], always_on=client.always_on) for name, client in clients.items()],
        managed=compute.managed(config),
        auto_stop_minutes=config.compute.auto_stop_minutes,
        session=compute.current_session(db),
        last=latest[0] if latest else None,
        not_ready_reason=compute.not_ready_reason(db, config),
    )


@router.get("/instances")
def list_instances(clients: ComputeDep) -> InstancesResponse:
    """Every enabled backend's targets, from the providers (a few seconds: the Brev CLI, ssh to the GB10). A backend
    that fails (no VPN, not logged in) is reported in errors, and the others are still listed."""
    instances, errors = [], []
    for name, client in clients.items():
        try:
            instances += client.instances()
        except ComputeError as e:
            errors.append(BackendError(backend=name, message=str(e)))
    return InstancesResponse(instances=instances, errors=errors)


@router.post("/start", status_code=202)
def start_session(body: StartSessionRequest, db: DbDep, config: ConfigDep, clients: ComputeDep) -> ComputeSession:
    """Start a Brev instance, or connect the GB10, for the sim. 422 for a backend that isn't enabled, 404 for an unknown
    target, 409 while another target's session is active."""
    client = clients.get(body.backend)
    if client is None:
        raise HTTPException(422, f"COMPUTE_BACKENDS doesn't include {body.backend} (it's {config.compute.backends})")
    with _http_errors():
        return compute.start_session(db, config, client, body.instance)


@router.post("/stop", status_code=202)
def stop_session(db: DbDep, config: ConfigDep) -> ComputeSession:
    """End the current session: stop its Brev instance, or disconnect the GB10 (its sim server keeps running). 409 when
    none is active."""
    with _http_errors():
        return compute.stop_session(db, config)


@router.get("/sessions")
def list_sessions(db: DbDep, limit: int = Query(20, ge=1, le=200)) -> list[ComputeSession]:
    """Past and current sessions, latest first: when each target was connected, and why it ended."""
    return compute.list_sessions(db, limit)


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except compute.InstanceNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except (compute.ComputeBusyError, compute.NoSessionError) as e:
        raise HTTPException(409, str(e)) from None
    except ComputeError as e:
        raise HTTPException(502, str(e)) from None
