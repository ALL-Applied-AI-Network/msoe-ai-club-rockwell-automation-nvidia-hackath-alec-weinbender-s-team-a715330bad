"""clips: grasps of a finished experiment's final designs, filmed in Isaac Sim

One row per clip (api/models/clip.py): which design at which offset, its status while its worker records it, the
recording's outcome against the job's stored one, and the views it has. The videos are files under the job's outputs.
A new table; nothing else changes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20 16:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("design", sa.String(), nullable=False),
        sa.Column("dx", sa.Double(), nullable=False),
        sa.Column("dy", sa.Double(), nullable=False),
        sa.Column("yaw_deg", sa.Double(), nullable=False),
        sa.Column("status", sa.Enum("queued", "recording", "ready", "failed", native_enum=False), nullable=False),
        sa.Column("views", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.Enum("held", "missed", native_enum=False), nullable=True),
        sa.Column("result", sa.Enum("held", "missed", native_enum=False), nullable=True),
        sa.Column("duration_s", sa.Double(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("created", sa.Double(), nullable=False),
        sa.Column("recorded", sa.Double(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("clips")
