import os

from fastapi import APIRouter
from pydantic import BaseModel

from api.dependencies import ConfigDep
from api.models.design import SPACE

router = APIRouter(prefix="/api", tags=["meta"])


class MetaResponse(BaseModel):
    templates: dict[str, dict[str, tuple[float, float]]]  # the design space: template -> parameter -> (min, max)
    llm: str  # active backends
    sim: str
    cpus: int | None


@router.get("/meta")
def get_meta(config: ConfigDep) -> MetaResponse:
    return MetaResponse(templates=SPACE, llm=config.llm.backend, sim=config.sim.backend, cpus=os.cpu_count())
