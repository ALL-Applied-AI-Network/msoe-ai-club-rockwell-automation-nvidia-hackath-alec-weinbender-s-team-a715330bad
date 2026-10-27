"""landing: how far each grasp moved the part before the jaws closed

The sim server reports it since 2026-10-26 (a finger landing on the part, risk 5 in CONTEXT.md), as [shift_mm, turn_deg]
per grid point, and a grasp that moved the part too far scores as a miss (api/models/task.py). The new nullable column
on both trial tables stores it. Rows from before are NULL: not measured, scored as they were. Other poses' landings are
inside pose_outcomes (JSON), which needs no change.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-26 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("trials", "evaluation_trials"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("landing", sa.JSON(), nullable=True))


def downgrade() -> None:
    for table in ("trials", "evaluation_trials"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("landing")
