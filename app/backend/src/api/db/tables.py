"""The database schema: one class per table.

Rows mirror the domain models in api/models without being them: rows also hold storage-only columns, and the models
are what services return. Value types come from api/models (Part and JobConfig as typed JSON, the status literals),
and tests/db/test_tables.py checks every model field against its table. Change a table only together with a migration:

    uv run --package backend alembic -c app/backend/alembic.ini revision --autogenerate -m "what changed"
"""

import time
from typing import Any

from pydantic import BaseModel
from sqlalchemy import JSON, TypeDecorator, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from api.models.job import JobConfig, JobStatus
from api.models.part import Part
from api.models.review import ReviewStatus


class PydanticJSON(TypeDecorator):
    """A JSON column holding one pydantic model: validated on the way in and out, so its shape can't drift."""

    impl = JSON
    cache_ok = True

    def __init__(self, model: type[BaseModel]):
        super().__init__()
        self.model = model

    def process_bind_param(self, value: BaseModel | None, dialect) -> dict | None:
        return None if value is None else self.model.model_validate(value).model_dump(mode="json")

    def process_result_value(self, value: dict | None, dialect) -> BaseModel | None:
        return None if value is None else self.model.model_validate(value)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, float]: JSON, dict[str, Any]: JSON, list[bool]: JSON, list[dict[str, Any]]: JSON}


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    created: Mapped[float] = mapped_column(default=time.time)
    status: Mapped[JobStatus]
    part_name: Mapped[str]
    part_path: Mapped[str | None]
    part: Mapped[Part] = mapped_column(PydanticJSON(Part))
    task: Mapped[str]
    config: Mapped[JobConfig] = mapped_column(PydanticJSON(JobConfig))
    n_done: Mapped[int] = mapped_column(default=0)
    n_total: Mapped[int] = mapped_column(default=0)
    stage: Mapped[str | None]
    best_value: Mapped[float | None]
    best_trial: Mapped[int | None]
    error: Mapped[str | None]
    cancel_requested: Mapped[int] = mapped_column(default=0)
    pid: Mapped[int | None]  # of the worker process running the job
    finished: Mapped[float | None]


class TrialRow(Base):
    __tablename__ = "trials"
    __table_args__ = (UniqueConstraint("job_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str]
    number: Mapped[int]
    round: Mapped[int]
    kind: Mapped[str]
    params: Mapped[dict[str, float]]
    success_rate: Mapped[float]
    capture_radius_mm: Mapped[float | None]
    n_grasps: Mapped[int]
    n_success: Mapped[int]
    held: Mapped[list[bool]]  # one result per point of the job's offset grid (its definition is in run_meta)
    duration: Mapped[float]  # seconds of the round's sim time, per design
    created: Mapped[float] = mapped_column(default=time.time)


class ResultRow(Base):
    __tablename__ = "results"

    job_id: Mapped[str] = mapped_column(primary_key=True)
    trial_number: Mapped[int]
    kind: Mapped[str]
    params: Mapped[dict[str, float]]
    grasp_pose: Mapped[dict[str, Any]]
    predicted_success: Mapped[float]
    capture_radius_mm: Mapped[float | None]
    comparison: Mapped[list[dict[str, Any]]]
    scad_path: Mapped[str]
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


class PhysicalTrialRow(Base):
    __tablename__ = "physical_trials"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str]
    created: Mapped[float] = mapped_column(default=time.time)
    finger: Mapped[str]
    success: Mapped[int]
    placement_error_mm: Mapped[float | None]
    cycle_time_s: Mapped[float | None]
    recovered: Mapped[int]
    operator_intervention: Mapped[int]
    notes: Mapped[str]
