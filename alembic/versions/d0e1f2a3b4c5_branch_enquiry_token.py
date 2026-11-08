"""branch enquiry token (public enquiry form link / QR)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-07 10:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("org_branches", sa.Column("enquiry_token", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_org_branches_enquiry_token", "org_branches", ["enquiry_token"])


def downgrade() -> None:
    op.drop_constraint("uq_org_branches_enquiry_token", "org_branches", type_="unique")
    op.drop_column("org_branches", "enquiry_token")
