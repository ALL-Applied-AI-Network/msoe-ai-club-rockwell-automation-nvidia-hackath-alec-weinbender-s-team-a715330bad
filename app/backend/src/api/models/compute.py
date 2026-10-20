"""The GPU targets the sim server runs on, as the app manages them: the instances each compute backend offers (Brev's are
created in its console, never here; the MSOE GB10 is one machine), and sessions. A session connects one target to the
app's SIM_URL. On Brev it starts the instance and stops it when asked or after COMPUTE_AUTO_STOP_MINUTES without a job;
the GB10 is always on and shared with other teams, so a session there only starts the sim server if it isn't running and
disconnects, leaving it running. Sessions are kept after they end, as a log of GPU time."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

ComputeBackend = Literal["mock", "brev", "gb10"]
COMPUTE_BACKENDS: tuple[ComputeBackend, ...] = ("mock", "brev", "gb10")
BACKEND_LABELS: dict[ComputeBackend, str] = {"mock": "Mock", "brev": "Brev", "gb10": "MSOE GB10"}
InstanceState = Literal["running", "starting", "stopping", "stopped", "other"]
SessionStatus = Literal["starting", "ready", "stopping", "stopped", "failed"]
ACTIVE_SESSION_STATUSES: tuple[SessionStatus, ...] = ("starting", "ready", "stopping")
StopReason = Literal["user", "idle", "external", "failed"]  # external: stopped outside the app (e.g. the Brev console)


class ComputeInstance(BaseModel):
    """One target a backend offers, as its provider reports it. status is the provider's own word (Brev: RUNNING,
    STOPPED, DEPLOYING, ...; the GB10: AVAILABLE, or BUSY with other GPU processes) and state what it means here."""

    backend: ComputeBackend
    name: str
    id: str
    status: str
    state: InstanceState
    gpu: str | None = None  # e.g. "RTX PRO 4500"; None when the provider doesn't say (Brev omits it while stopped)
    instance_type: str | None = None
    always_on: bool = False  # nothing to start or stop (the GB10): the app connects and disconnects
    # The GB10, shared: GPU processes besides our sim server (another team's, or a teammate's run). None elsewhere.
    other_gpu_processes: int | None = None


class ComputeSession(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # read straight from api.db.tables rows

    id: int
    backend: ComputeBackend
    instance: str
    status: SessionStatus
    message: str | None = None  # what the session is doing now, or why it failed, for the UI
    pid: int | None = None  # of the session process (api.compute_worker)
    stop_requested: int = 0
    requested: float  # when the user asked for it
    ready_at: float | None = None  # when the sim answered through the tunnel
    last_active: float | None = None  # the last time a job or a prediction was seen using it
    stopped_at: float | None = None
    stop_reason: StopReason | None = None
