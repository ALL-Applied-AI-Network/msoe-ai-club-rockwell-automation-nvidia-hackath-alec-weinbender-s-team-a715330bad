from fastapi import APIRouter
from pydantic import BaseModel

from sim_server.dependencies import SceneDep, SimQueueDep

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str = "ok"
    queued: int  # batches waiting for the main thread, not counting the one running
    envs: int  # 1: the reference path; more: the vectorised path
    device: str
    friction_combine: str


@router.get("/health")
async def health(scene: SceneDep, sim_queue: SimQueueDep) -> HealthResponse:
    """Answers while a batch runs: it never touches Isaac."""
    return HealthResponse(queued=sim_queue.queued, **scene.describe())
