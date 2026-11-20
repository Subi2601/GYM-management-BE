"""add encrypted employee UPI ID

Revision ID: a18f7d2c94b1
Revises: 6246f359102a
Create Date: 2026-11-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a18f7d2c94b1"
down_revision: Union[str, None] = "6246f359102a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_employees", sa.Column("upi_id_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_employees", "upi_id_enc")
