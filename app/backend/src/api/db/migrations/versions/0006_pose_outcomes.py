"""pose_outcomes: a trial's outcomes in every resting pose after the primary

A job can cover several resting poses of its part (api/models/job_pose.py), and every design is simulated in each.
held, in_hand and held_after_transport stay the primary pose's; the new nullable column holds the others' outcomes.
Rows from before are NULL: one pose. The poses themselves are in the job's plan (JSON), which needs no change.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trials") as batch:
        batch.add_column(sa.Column("pose_outcomes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trials") as batch:
        batch.drop_column("pose_outcomes")
