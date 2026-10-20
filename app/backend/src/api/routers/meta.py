import os

from fastapi import APIRouter
from pydantic import BaseModel

from api.dependencies import ConfigDep
from api.models.design import PARAMS

router = APIRouter(prefix="/api", tags=["meta"])


class MetaResponse(BaseModel):
    parameters: dict[str, str]  # the design parameters the optimizer searches, and what each one is
    llm: str  # active backends
    sim: str
    cpus: int | None


@router.get("/meta")
def get_meta(config: ConfigDep) -> MetaResponse:
    return MetaResponse(parameters=PARAMS, llm=config.llm.backend, sim=config.sim.backend, cpus=os.cpu_count())
