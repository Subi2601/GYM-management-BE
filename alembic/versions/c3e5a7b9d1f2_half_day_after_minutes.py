"""staff half day when this late (Gym settings)

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
Create Date: 2026-11-08 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e5a7b9d1f2"
down_revision: Union[str, None] = "b2d4f6a8c0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("org_organizations", sa.Column("half_day_after_minutes", sa.SmallInteger(), nullable=False,
                                                 server_default=sa.text("30")))


def downgrade() -> None:
    op.drop_column("org_organizations", "half_day_after_minutes")
