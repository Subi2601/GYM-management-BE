"""common plans / offers: branch_id NULL = shared by every branch of the gym

Revision ID: c8d3f5a7b9e1
Revises: b7c2e4f6a8d0
Create Date: 2026-11-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c8d3f5a7b9e1"
down_revision: Union[str, None] = "b7c2e4f6a8d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("plan_plans", "branch_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.alter_column("plan_offers", "branch_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    # Common rows have no branch to go back to — refuse instead of guessing one.
    bind = op.get_bind()
    for table in ("plan_plans", "plan_offers"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} WHERE branch_id IS NULL LIMIT 1")).first():
            raise RuntimeError(f"{table} has common (all-branch) rows; move them to a branch before downgrading")
    op.alter_column("plan_offers", "branch_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.alter_column("plan_plans", "branch_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
