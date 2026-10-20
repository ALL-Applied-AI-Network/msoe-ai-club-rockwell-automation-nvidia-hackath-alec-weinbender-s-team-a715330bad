"""FastAPI dependencies: hand routers the resources that main.py's lifespan created. Tests swap them through
app.dependency_overrides."""

from typing import Annotated

from fastapi import Depends, Request

from api.clients.cad import CadClient
from api.clients.compute import ComputeClient
from api.clients.database import DatabaseClient
from api.config import AppConfig
from api.models.compute import ComputeBackend


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> DatabaseClient:
    return request.app.state.db


def get_cad(request: Request) -> CadClient:
    return request.app.state.cad


def get_compute(request: Request) -> dict[ComputeBackend, ComputeClient]:
    """One client per enabled GPU target backend (COMPUTE_BACKENDS)."""
    return request.app.state.compute


ConfigDep = Annotated[AppConfig, Depends(get_config)]
DbDep = Annotated[DatabaseClient, Depends(get_db)]
CadDep = Annotated[CadClient, Depends(get_cad)]
ComputeDep = Annotated[dict[ComputeBackend, ComputeClient], Depends(get_compute)]
