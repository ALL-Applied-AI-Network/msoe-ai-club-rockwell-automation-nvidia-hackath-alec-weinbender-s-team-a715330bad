"""The database schema: one class per table.

Rows mirror the domain models in api/models without being them: rows also hold storage-only columns, and the models
are what services return. Value types come from api/models (the part, spec, plan and profile as typed JSON, the status
literals), and tests/db/test_tables.py checks every model field against its table. Change a table only together with a
migration:

    uv run --package backend alembic -c app/backend/alembic.ini revision --autogenerate -m "what changed"
"""

import time
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import JSON, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from api.models.cell_profile import CellProfile
from api.models.clip import ClipOutcome, ClipStatus
from api.models.compute import ComputeBackend, SessionStatus, StopReason
from api.models.job import JobStatus
from api.models.job_spec import JobSpec
from api.models.outcome import Outcomes
from api.models.part import Part
from api.models.part_cad import PartCad
from api.models.resting_pose import RestingPose
from api.models.review import ReviewStatus
from api.models.search_plan import JobPlan
from api.models.test_plan import PlannedTrial


class PydanticJSON(TypeDecorator):
    """A JSON column holding a pydantic-typed value (a model, or e.g. a list of models): validated on the way in and
    out, so its shape can't drift."""

    impl = JSON
    cache_ok = True

    def __init__(self, model: Any):
        super().__init__()
        self.model = model
        self._adapter = TypeAdapter(model)

    def process_bind_param(self, value: Any, dialect) -> Any:
        return None if value is None else self._adapter.dump_python(self._adapter.validate_python(value), mode="json")

    def process_result_value(self, value: Any, dialect) -> Any:
        return None if value is None else self._adapter.validate_python(value)


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, float]: JSON,
        dict[str, Any]: JSON,
        list[bool]: JSON,
        list[str]: JSON,
        list[Any]: JSON,
        list[dict[str, Any]]: JSON,
    }


class PartRow(Base):
    """An uploaded part (api/models/part_record.py)."""

    __tablename__ = "parts"

    id: Mapped[str] = mapped_column(primary_key=True)
    created: Mapped[float] = mapped_column(default=time.time)
    name: Mapped[str]
    file_path: Mapped[str]
    source: Mapped[str]
    units: Mapped[str]
    measured: Mapped[PartCad] = mapped_column(PydanticJSON(PartCad))
    material: Mapped[str | None]
    density_g_cm3: Mapped[float | None]
    surface: Mapped[str] = mapped_column(default="smooth")
    mass_g: Mapped[float | None]
    mass_unit: Mapped[str] = mapped_column(default="g")
    fragile: Mapped[bool] = mapped_column(default=False)
    max_grip_force_n: Mapped[float | None]
    clearance_mm: Mapped[float | None]
    pose: Mapped[RestingPose | None] = mapped_column(PydanticJSON(RestingPose))


class CellProfileRow(Base):
    """One version of a named cell profile. Editing a profile adds a row; jobs point at the row they used."""

    __tablename__ = "cell_profiles"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    version: Mapped[int]
    created: Mapped[float] = mapped_column(default=time.time)
    profile: Mapped[CellProfile] = mapped_column(PydanticJSON(CellProfile))


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    experiment_number: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str]
    created: Mapped[float] = mapped_column(default=time.time)
    status: Mapped[JobStatus]
    part_id: Mapped[str]
    cell_profile_id: Mapped[int]
    sim_backend: Mapped[str]
    spec: Mapped[JobSpec] = mapped_column(PydanticJSON(JobSpec))
    part: Mapped[Part] = mapped_column(PydanticJSON(Part))
    plan: Mapped[JobPlan] = mapped_column(PydanticJSON(JobPlan))
    n_done: Mapped[int] = mapped_column(default=0)
    n_total: Mapped[int] = mapped_column(default=0)
    round: Mapped[int] = mapped_column(default=0)
    n_rounds: Mapped[int] = mapped_column(default=0)
    best_value: Mapped[float | None]
    best_trial: Mapped[int | None]
    error: Mapped[str | None]
    failure: Mapped[str | None]
    failed_step: Mapped[int | None]
    cancel_requested: Mapped[int] = mapped_column(default=0)
    pid: Mapped[int | None]  # of the worker process running the job
    finished: Mapped[float | None]
    duplicated_from: Mapped[str | None]
    print_designs: Mapped[list[str]] = mapped_column(default=list)


class TrialRow(Base):
    """One design at every point of one grid, with the raw outcomes (see api/models/outcome.py)."""

    __tablename__ = "trials"
    __table_args__ = (UniqueConstraint("job_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str]
    number: Mapped[int]
    round: Mapped[int]
    search: Mapped[str]
    grid: Mapped[str]  # "search" or "final"; the grids themselves are in the job's plan
    kind: Mapped[str]
    label: Mapped[str | None]
    params: Mapped[dict[str, Any] | None]
    success_rate: Mapped[float]
    capture_radius_mm: Mapped[float | None]
    n_grasps: Mapped[int]
    n_success: Mapped[int]
    held: Mapped[list[bool]]
    in_hand: Mapped[list[Any]]  # [dx, dy, dz, tilt, yaw] or null per grid point
    held_after_transport: Mapped[list[bool] | None]
    # Every resting pose's outcomes after the primary's (held ... above), in the job's pose order; NULL for one pose
    pose_outcomes: Mapped[list[Outcomes] | None] = mapped_column(PydanticJSON(list[Outcomes]))
    duration: Mapped[float]  # seconds of the round's sim time, per design
    created: Mapped[float] = mapped_column(default=time.time)


class ResultRow(Base):
    __tablename__ = "results"

    job_id: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str]
    trial_number: Mapped[int]
    search: Mapped[str]
    kind: Mapped[str]
    params: Mapped[dict[str, Any] | None]
    grasp_pose: Mapped[dict[str, Any]]
    predicted_success: Mapped[float]
    capture_radius_mm: Mapped[float | None]
    cad_files: Mapped[dict[str, Any]]  # "step", "stl_left", "stl_right", "print_sheet" -> path
    checks: Mapped[list[dict[str, Any]]]
    created: Mapped[float] = mapped_column(default=time.time)


class RunMetaRow(Base):
    __tablename__ = "run_meta"

    job_id: Mapped[str] = mapped_column(primary_key=True)
    meta: Mapped[dict[str, Any]]


class ReviewRow(Base):
    __tablename__ = "reviews"

    job_id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[ReviewStatus]
    reviewer: Mapped[str]
    notes: Mapped[str]
    created: Mapped[float] = mapped_column(default=time.time)


class PrintedFingerRow(Base):
    __tablename__ = "printed_fingers"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str]
    finger_id: Mapped[str]
    design_label: Mapped[str]
    side: Mapped[str]
    material: Mapped[str]
    print_date: Mapped[str | None]
    notes: Mapped[str] = mapped_column(default="")
    created: Mapped[float] = mapped_column(default=time.time)


class TestPlanRow(Base):
    __tablename__ = "test_plans"
    __test__ = False  # not a pytest class

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str]
    created: Mapped[float] = mapped_column(default=time.time)
    seed: Mapped[int]
    designs: Mapped[list[str]]
    rows: Mapped[list[PlannedTrial]] = mapped_column(PydanticJSON(list[PlannedTrial]))
    prediction_status: Mapped[str] = mapped_column(default="pending")
    prediction_error: Mapped[str | None]


class ComputeSessionRow(Base):
    """One GPU instance brought up for the sim and later stopped (api/models/compute.py); kept as a log of GPU time."""

    __tablename__ = "compute_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    backend: Mapped[ComputeBackend]
    instance: Mapped[str]
    status: Mapped[SessionStatus]
    message: Mapped[str | None]
    pid: Mapped[int | None]  # of the session process (api.compute_worker)
    stop_requested: Mapped[int] = mapped_column(default=0)
    requested: Mapped[float] = mapped_column(default=time.time)
    ready_at: Mapped[float | None]
    last_active: Mapped[float | None]
    stopped_at: Mapped[float | None]
    stop_reason: Mapped[StopReason | None]


class ClipRow(Base):
    """One grasp of a final design, filmed by the sim server (api/models/clip.py). The videos are files under the job's
    outputs (clips/<id>_<view>.mp4)."""

    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str]
    design: Mapped[str]  # the final label: D1, ..., STOCK, IMP
    dx: Mapped[float]  # the offset, mm and degrees
    dy: Mapped[float]
    yaw_deg: Mapped[float]
    status: Mapped[ClipStatus]
    views: Mapped[list[str]]
    outcome: Mapped[ClipOutcome | None]
    result: Mapped[ClipOutcome | None]
    duration_s: Mapped[float | None]
    error: Mapped[str | None]
    pid: Mapped[int | None]  # of its worker (python -m api.worker <job_id> clip <id>)
    created: Mapped[float] = mapped_column(default=time.time)
    recorded: Mapped[float | None]


class PhysicalTrialRow(Base):
    __tablename__ = "physical_trials"
    __table_args__ = (UniqueConstraint("job_id", "trial_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str]
    plan_id: Mapped[int | None]
    trial_id: Mapped[str]
    design_label: Mapped[str]
    finger_id: Mapped[str | None]
    kind: Mapped[str]
    offset_x_mm: Mapped[float]
    offset_y_mm: Mapped[float]
    yaw_deg: Mapped[float]
    repeat: Mapped[int] = mapped_column(default=1)
    outcome: Mapped[str]
    in_tolerance: Mapped[bool | None]
    notes: Mapped[str] = mapped_column(default="")
    video_link: Mapped[str | None]
    operator: Mapped[str | None]
    timestamp: Mapped[str | None]
    history: Mapped[list[dict[str, Any]]] = mapped_column(default=list)
    created: Mapped[float] = mapped_column(default=time.time)
