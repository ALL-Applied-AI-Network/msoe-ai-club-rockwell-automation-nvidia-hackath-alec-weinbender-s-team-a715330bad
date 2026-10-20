"""The two seams that can drift: domain models vs tables, and tables vs migrations."""

import types
from typing import Union, get_args, get_origin

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from api.db.tables import (
    Base,
    CellProfileRow,
    ComputeSessionRow,
    JobRow,
    PartRow,
    PhysicalTrialRow,
    PrintedFingerRow,
    ResultRow,
    ReviewRow,
    TestPlanRow,
    TrialRow,
)
from api.models.cell_profile import CellProfileVersion
from api.models.compute import ComputeSession
from api.models.job import Job, JobResult, Trial
from api.models.part_record import PartRecord
from api.models.physical_trial import PhysicalTrial
from api.models.printed_finger import PrintedFinger
from api.models.review import Review
from api.models.test_plan import TestPlan

MODEL_TABLE_PAIRS = [
    (PartRecord, PartRow),
    (CellProfileVersion, CellProfileRow),
    (Job, JobRow),
    (Trial, TrialRow),
    (JobResult, ResultRow),
    (Review, ReviewRow),
    (PrintedFinger, PrintedFingerRow),
    (TestPlan, TestPlanRow),
    (PhysicalTrial, PhysicalTrialRow),
    (ComputeSession, ComputeSessionRow),
]


def _accepts_none(annotation) -> bool:
    return get_origin(annotation) in (Union, types.UnionType) and type(None) in get_args(annotation)


@pytest.mark.parametrize(("model", "row"), MODEL_TABLE_PAIRS, ids=lambda cls: cls.__name__)
def test_every_model_field_has_a_matching_column(model, row):
    columns = row.__table__.columns
    for name, field in model.model_fields.items():
        assert name in columns, f"{model.__name__}.{name} has no column in table {row.__tablename__}"
        assert columns[name].nullable == _accepts_none(field.annotation), (
            f"{model.__name__}.{name} and {row.__tablename__}.{name} disagree on whether it can be null"
        )


def test_migrations_build_exactly_the_tables(db):
    with db.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)

    assert diff == [], "tables.py changed without a migration; run: alembic revision --autogenerate -m '...'"
