"""grid-scored trials and batch BO results; drop LLM suggestions

Jobs from before this revision were scored by the old template design space and a made-up mock, so their rows don't
fit the new tables and mean nothing anymore. This is a demo database: the upgrade clears every job (and its reviews and
physical trials) instead of converting them. The downgrade restores the old schema, empty.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19 18:14:42.844814
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import sqlite

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_TABLES = ("jobs", "trials", "results", "run_meta", "reviews", "physical_trials")


def upgrade() -> None:
    for table in JOB_TABLES:
        op.execute(sa.text(f"DELETE FROM {table}"))
    op.drop_table("suggestions")
    with op.batch_alter_table("results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(), nullable=False))
        batch_op.add_column(sa.Column("capture_radius_mm", sa.Double(), nullable=True))
        batch_op.add_column(sa.Column("comparison", sa.JSON(), nullable=False))
        batch_op.drop_column("ci_low")
        batch_op.drop_column("ci_high")
        batch_op.drop_column("template")

    with op.batch_alter_table("trials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("round", sa.Integer(), nullable=False))
        batch_op.add_column(sa.Column("kind", sa.String(), nullable=False))
        batch_op.add_column(sa.Column("capture_radius_mm", sa.Double(), nullable=True))
        batch_op.add_column(sa.Column("held", sa.JSON(), nullable=False))
        batch_op.drop_column("suggestion_id")
        batch_op.drop_column("template")
        batch_op.drop_column("pruned")


def downgrade() -> None:
    for table in JOB_TABLES:
        op.execute(sa.text(f"DELETE FROM {table}"))
    with op.batch_alter_table("trials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pruned", sa.INTEGER(), nullable=False))
        batch_op.add_column(sa.Column("template", sa.VARCHAR(), nullable=False))
        batch_op.add_column(sa.Column("suggestion_id", sa.INTEGER(), nullable=True))
        batch_op.drop_column("held")
        batch_op.drop_column("capture_radius_mm")
        batch_op.drop_column("kind")
        batch_op.drop_column("round")

    with op.batch_alter_table("results", schema=None) as batch_op:
        batch_op.add_column(sa.Column("template", sa.VARCHAR(), nullable=False))
        batch_op.add_column(sa.Column("ci_high", sa.DOUBLE(), nullable=False))
        batch_op.add_column(sa.Column("ci_low", sa.DOUBLE(), nullable=False))
        batch_op.drop_column("comparison")
        batch_op.drop_column("capture_radius_mm")
        batch_op.drop_column("kind")

    op.create_table(
        "suggestions",
        sa.Column("id", sa.INTEGER(), nullable=False),
        sa.Column("job_id", sa.VARCHAR(), nullable=False),
        sa.Column("idx", sa.INTEGER(), nullable=False),
        sa.Column("template", sa.VARCHAR(), nullable=False),
        sa.Column("params", sqlite.JSON(), nullable=False),
        sa.Column("rationale", sa.VARCHAR(), nullable=True),
        sa.Column("source", sa.VARCHAR(), nullable=False),
        sa.Column("model", sa.VARCHAR(), nullable=True),
        sa.Column("raw_response", sa.VARCHAR(), nullable=True),
        sa.Column("created", sa.DOUBLE(), nullable=False),
        sa.Column("trial_number", sa.INTEGER(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
