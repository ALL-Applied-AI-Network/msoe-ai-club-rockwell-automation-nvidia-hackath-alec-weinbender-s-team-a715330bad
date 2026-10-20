"""FastAPI dependencies: hand routers the Scene and SimQueue that app.create_app() stored on app.state. Tests swap them
through app.dependency_overrides or by building the app with fakes."""

from typing import Annotated

from fastapi import Depends, Request

from sim_server.scene import Scene
from sim_server.sim_queue import SimQueue


def get_scene(request: Request) -> Scene:
    return request.app.state.scene


def get_sim_queue(request: Request) -> SimQueue:
    return request.app.state.sim_queue


SceneDep = Annotated[Scene, Depends(get_scene)]
SimQueueDep = Annotated[SimQueue, Depends(get_sim_queue)]
