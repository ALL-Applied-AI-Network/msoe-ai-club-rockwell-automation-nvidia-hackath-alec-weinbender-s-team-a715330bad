"""FastAPI dependencies: hand routers the Scene, SimQueue and RecentBatches that app.create_app() stored on app.state.
Tests swap them through app.dependency_overrides or by building the app with fakes."""

from typing import Annotated

from fastapi import Depends, Request

from sim_server.recent_batches import RecentBatches
from sim_server.scene import Scene
from sim_server.sim_queue import SimQueue


def get_scene(request: Request) -> Scene:
    return request.app.state.scene


def get_sim_queue(request: Request) -> SimQueue:
    return request.app.state.sim_queue


def get_recent_batches(request: Request) -> RecentBatches:
    return request.app.state.recent_batches


SceneDep = Annotated[Scene, Depends(get_scene)]
SimQueueDep = Annotated[SimQueue, Depends(get_sim_queue)]
RecentBatchesDep = Annotated[RecentBatches, Depends(get_recent_batches)]
