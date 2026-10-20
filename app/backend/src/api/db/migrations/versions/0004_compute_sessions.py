"""compute sessions: the GPU instances the app brings up for the sim and stops again

One row per session (api/models/compute.py): which instance, its status while it starts, serves and stops, the session
process, and when it was requested, ready, last used and stopped, with why. A new table; nothing else changes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20 10:21:45.713001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compute_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("backend", sa.Enum("mock", "brev", "gb10", native_enum=False), nullable=False),
        sa.Column("instance", sa.String(), nullable=False),
        sa.Column("status", sa.Enum("starting", "ready", "stopping", "stopped", "failed", native_enum=False), nullable=False),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("stop_requested", sa.Integer(), nullable=False),
        sa.Column("requested", sa.Double(), nullable=False),
        sa.Column("ready_at", sa.Double(), nullable=True),
        sa.Column("last_active", sa.Double(), nullable=True),
        sa.Column("stopped_at", sa.Double(), nullable=True),
        sa.Column("stop_reason", sa.Enum("user", "idle", "external", "failed", native_enum=False), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("compute_sessions")
