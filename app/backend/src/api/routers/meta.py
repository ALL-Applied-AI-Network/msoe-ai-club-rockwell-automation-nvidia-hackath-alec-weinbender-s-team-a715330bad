"""Catalogs the input steps need, read from the domain models so the wizard never keeps its own copy: materials and
surfaces (step 1), task kinds and transport speeds (step 3), finger families with their parameter schemas (step 6),
error presets (step 7), and the active backends, with the badge every result from this sim carries."""

import os
from typing import Any, Literal, get_args

from fastapi import APIRouter
from pydantic import BaseModel

from api.clients.sim import sim_badge
from api.dependencies import ConfigDep
from api.models.error_model import PRESETS
from api.models.family import FAMILIES
from api.models.job_spec import SimBackend
from api.models.material import MATERIALS, SURFACE_FACTORS
from api.models.part_record import GRAMS_PER, MassUnit
from api.models.resting_pose import POSE_CUTOFF
from api.models.task import TASK_LABELS, TaskKind, Transport

router = APIRouter(prefix="/api", tags=["meta"])

# The Task fields each kind needs (api/models/task.py: Task._tolerances checks them; tests/routers/test_meta.py keeps
# the two in step).
TASK_TOLERANCES: dict[str, list[str]] = {
    "drop": [],
    "place": ["offset_tolerance_mm"],
    "insert": ["offset_tolerance_mm", "tilt_tolerance_deg"],
}
# The transport move (decision D6): 120 mm along base +X, across the jaws, in this long, then 0.5 s to settle.
TRANSPORT_MM, TRANSPORT_SETTLE_S = 120.0, 0.5
TRANSPORT_MOVE_S: dict[str, float] = {"slow": 1.2, "normal": 0.6, "fast": 0.3}


class MaterialInfo(BaseModel):
    name: str
    label: str
    density_g_cm3: float | None  # None: the user enters it ("other")
    friction: tuple[float, float] | None  # static, dynamic against the printed pad; None: the cell profile's pad friction


class SurfaceInfo(BaseModel):
    name: str
    label: str
    friction_factor: float  # scales the material's friction


class FamilyInfo(BaseModel):
    name: str
    label: str
    status: Literal["built", "planned"]  # only built families can be ticked
    description: str
    only_for: str | None  # the parts it applies to, if not all
    fields: list[str]  # the parameters, in search order
    params_schema: dict[str, Any] | None  # JSON schema with each field's description, bounds and applies_to; None while planned


class ErrorPresetInfo(BaseModel):
    name: str
    label: str
    sigma_mm: float
    sigma_deg: float
    placeholder: bool  # until replaced by error measured on the real cell
    note: str


class TaskKindInfo(BaseModel):
    name: TaskKind
    label: str
    tolerances: list[str]  # the Task fields this kind needs


class TransportInfo(BaseModel):
    name: Transport
    label: str
    move_s: float
    distance_mm: float = TRANSPORT_MM
    settle_s: float = TRANSPORT_SETTLE_S


class MassUnitInfo(BaseModel):
    name: MassUnit
    grams: float  # one of this unit, in grams


class SimInfo(BaseModel):
    backend: Literal["mock", "http"]
    badge: SimBackend  # mock results are never predictions
    url: str | None


class MetaResponse(BaseModel):
    materials: list[MaterialInfo]
    surfaces: list[SurfaceInfo]
    families: list[FamilyInfo]
    error_presets: list[ErrorPresetInfo]
    task_kinds: list[TaskKindInfo]
    transports: list[TransportInfo]
    mass_units: list[MassUnitInfo]
    sim: SimInfo
    llm: str
    cpus: int | None
    demo_data: bool  # DEMO_DATA=true: generated demo data (mock results, made-up physical trials), not the real database
    pose_cutoff: float  # a stable resting pose at least this likely is "likely" (GET /api/parts/{id}/poses): ticked by default


@router.get("/meta")
def get_meta(config: ConfigDep) -> MetaResponse:
    return MetaResponse(
        materials=[
            MaterialInfo(name=name, label=m.label, density_g_cm3=m.density_g_cm3, friction=m.friction) for name, m in MATERIALS.items()
        ],
        surfaces=[SurfaceInfo(name=name, label=name.capitalize(), friction_factor=factor) for name, factor in SURFACE_FACTORS.items()],
        families=[
            FamilyInfo(
                name=f.name,
                label=f.label,
                status=f.status,
                description=f.description,
                only_for=f.only_for,
                fields=f.fields,
                params_schema=None if f.params is None else f.params.model_json_schema(),
            )
            for f in FAMILIES.values()
        ],
        error_presets=[
            ErrorPresetInfo(name=name, label=p.label, sigma_mm=p.sigma_mm, sigma_deg=p.sigma_deg, placeholder=p.placeholder, note=p.note)
            for name, p in PRESETS.items()
        ],
        task_kinds=[TaskKindInfo(name=kind, label=TASK_LABELS[kind], tolerances=TASK_TOLERANCES[kind]) for kind in get_args(TaskKind)],
        transports=[TransportInfo(name=name, label=name.capitalize(), move_s=TRANSPORT_MOVE_S[name]) for name in get_args(Transport)],
        mass_units=[MassUnitInfo(name=unit, grams=GRAMS_PER[unit]) for unit in get_args(MassUnit)],
        sim=SimInfo(backend=config.sim.backend, badge=sim_badge(config.sim.backend), url=config.sim.url),
        llm=config.llm.backend,
        cpus=os.cpu_count(),
        demo_data=config.demo_data,
        pose_cutoff=POSE_CUTOFF,
    )
