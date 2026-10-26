"""finger library, evaluation jobs and qualifications

Two kinds of job now share the jobs table: generation (the optimizer, as before) and evaluation (library fingers tried
on a part and ranked). jobs.kind tells them apart; every existing row is a generation job. An evaluation job's trials go
in their own table, evaluation_trials. New tables for the finger library (fingers), one finger on one part
(qualifications) and the real-robot sessions logged against it (real_sessions). Parts get an optional part number.
Nothing existing is cleared.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-26 00:46:15.492973
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_trials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("stage", sa.Enum("search", "final", native_enum=False), nullable=False),
        sa.Column("finger_id", sa.String(), nullable=False),
        sa.Column("pose_key", sa.String(), nullable=False),
        sa.Column("grasp_key", sa.String(), nullable=False),
        sa.Column("success_rate", sa.Double(), nullable=False),
        sa.Column("capture_radius_mm", sa.Double(), nullable=True),
        sa.Column("n_grasps", sa.Integer(), nullable=False),
        sa.Column("held", sa.JSON(), nullable=False),
        sa.Column("in_hand", sa.JSON(), nullable=False),
        sa.Column("held_after_transport", sa.JSON(), nullable=True),
        sa.Column("tip_height_mm", sa.Double(), nullable=True),
        sa.Column("jaw_close_mm", sa.Double(), nullable=True),
        sa.Column("duration", sa.Double(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "number"),
    )
    op.create_table(
        "fingers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("source", sa.Enum("stock", "generated", "uploaded", native_enum=False), nullable=False),
        sa.Column("cell_profile_name", sa.String(), nullable=False),
        sa.Column("family", sa.Enum("stock", "vpad", "flat", "imprint", "other", native_enum=False), nullable=False),
        sa.Column("material", sa.String(), nullable=False),
        sa.Column("pad_friction", sa.JSON(), nullable=False),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("built_for", sa.JSON(), nullable=True),
        sa.Column("design", sa.JSON(), nullable=True),
        sa.Column("cell_profile_id", sa.Integer(), nullable=True),
        sa.Column("origin_job_id", sa.String(), nullable=True),
        sa.Column("origin_label", sa.String(), nullable=True),
        sa.Column("origin_sim_backend", sa.String(), nullable=True),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("extent_mm", sa.JSON(), nullable=True),
        sa.Column("pieces", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
    )
    op.create_table(
        "qualifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("finger_id", sa.String(), nullable=False),
        sa.Column("part_id", sa.String(), nullable=False),
        sa.Column("prediction", sa.JSON(), nullable=True),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("updated", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finger_id", "part_id"),
    )
    op.create_table(
        "real_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("qualification_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Enum("natural", "commanded", native_enum=False), nullable=False),
        sa.Column("trials", sa.Integer(), nullable=False),
        sa.Column("successes", sa.Integer(), nullable=False),
        sa.Column("predicted_success", sa.Double(), nullable=True),
        sa.Column("notes", sa.String(), nullable=False),
        sa.Column("operator", sa.String(), nullable=True),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("created", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("kind", sa.Enum("generation", "evaluation", native_enum=False), nullable=False, server_default="generation")
        )
        batch_op.add_column(sa.Column("batch_id", sa.String(), nullable=True))

    with op.batch_alter_table("parts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("part_number", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("parts", schema=None) as batch_op:
        batch_op.drop_column("part_number")

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_column("batch_id")
        batch_op.drop_column("kind")

    op.drop_table("real_sessions")
    op.drop_table("qualifications")
    op.drop_table("fingers")
    op.drop_table("evaluation_trials")
