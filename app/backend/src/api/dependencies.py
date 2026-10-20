"""FastAPI dependencies: hand routers the resources that main.py's lifespan created. Tests swap them through
app.dependency_overrides."""

from typing import Annotated

from fastapi import Depends, Request

from api.clients.cad import CadClient
from api.clients.database import DatabaseClient
from api.config import AppConfig


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_db(request: Request) -> DatabaseClient:
    return request.app.state.db


def get_cad(request: Request) -> CadClient:
    return request.app.state.cad


ConfigDep = Annotated[AppConfig, Depends(get_config)]
DbDep = Annotated[DatabaseClient, Depends(get_db)]
CadDep = Annotated[CadClient, Depends(get_cad)]
