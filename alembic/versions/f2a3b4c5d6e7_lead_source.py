"""lead source (walk-in, phone call, enquiry form, ...)

Revision ID: f2a3b4c5d6e7
Revises: 31284e265414
Create Date: 2026-11-05 10:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "31284e265414"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing leads stay NULL ("not recorded") — their channel was never captured.
    op.add_column("lead_leads", sa.Column("source", sa.String(length=20), nullable=True))
    op.create_index("ix_lead_leads_source", "lead_leads", ["source"])


def downgrade() -> None:
    op.drop_index("ix_lead_leads_source", table_name="lead_leads")
    op.drop_column("lead_leads", "source")
