from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from sim_server.dependencies import SceneDep, SimQueueDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """The queue plus the scene's describe(): the fields below always, and whatever else it reports passed through
    (physics_dt, solver_position_iterations, solver_velocity_iterations, contact_offset_mm, rest_offset_mm, ...)."""

    model_config = ConfigDict(extra="allow")

    status: str = "ok"
    queued: int  # batches waiting for the main thread, not counting the one running
    envs: int  # 1: the reference path; more: the vectorised path
    device: str
    friction_combine: str


@router.get("/health")
async def health(scene: SceneDep, sim_queue: SimQueueDep) -> HealthResponse:
    """Answers while a batch runs: describe() returns values recorded at startup and never touches Isaac."""
    return HealthResponse(queued=sim_queue.queued, **scene.describe())
