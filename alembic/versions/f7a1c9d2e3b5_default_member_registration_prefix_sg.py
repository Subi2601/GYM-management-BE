"""Use SG as the member registration ID prefix for every gym.

Revision ID: f7a1c9d2e3b5
Revises: f6a1c9d2e3b4
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f7a1c9d2e3b5"
down_revision: Union[str, Sequence[str], None] = "f6a1c9d2e3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE org_organizations SET member_id_prefix = 'SG' "
               "WHERE member_id_prefix IS DISTINCT FROM 'SG'")


def downgrade() -> None:
    op.execute("UPDATE org_organizations SET member_id_prefix = code")
