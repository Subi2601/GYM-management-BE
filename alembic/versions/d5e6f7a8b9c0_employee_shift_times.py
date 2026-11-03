"""employee shift times: morning / evening from-to

Revision ID: d5e6f7a8b9c0
Revises: c7d2e8f9a0b1
Create Date: 2026-11-03 15:00:00

Nullable, so existing employees stay valid until their timings are entered.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c7d2e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("morning_start", "morning_end", "evening_start", "evening_end")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("staff_employees", sa.Column(name, sa.Time(), nullable=True))


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("staff_employees", name)
