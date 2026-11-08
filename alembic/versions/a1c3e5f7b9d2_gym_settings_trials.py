"""gym settings (trial, renewals, late grace) + lead trial class

Revision ID: a1c3e5f7b9d2
Revises: d0e1f2a3b4c5
Create Date: 2026-11-07 14:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c3e5f7b9d2"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ORG = [
    sa.Column("trial_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    sa.Column("trial_days", sa.SmallInteger(), nullable=False, server_default=sa.text("3")),
    sa.Column("trial_fee", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
    sa.Column("renewal_due_days", sa.SmallInteger(), nullable=False, server_default=sa.text("7")),
    sa.Column("renewal_overdue_days", sa.SmallInteger(), nullable=False, server_default=sa.text("30")),
    sa.Column("late_grace_minutes", sa.SmallInteger(), nullable=False, server_default=sa.text("10")),
]


def upgrade() -> None:
    for column in _ORG:
        op.add_column("org_organizations", column)
    mode = postgresql.ENUM(name="payment_mode", create_type=False)
    op.add_column("lead_leads", sa.Column("trial_start", sa.Date(), nullable=True))
    op.add_column("lead_leads", sa.Column("trial_end", sa.Date(), nullable=True))
    op.add_column("lead_leads", sa.Column("trial_fee", sa.Numeric(12, 2), nullable=True))
    op.add_column("lead_leads", sa.Column("trial_paid_on", sa.Date(), nullable=True))
    op.add_column("lead_leads", sa.Column("trial_payment_mode", mode, nullable=True))
    op.add_column("lead_leads", sa.Column("trial_visits", sa.SmallInteger(), nullable=False,
                                          server_default=sa.text("0")))
    op.add_column("lead_leads", sa.Column("trial_last_visit", sa.Date(), nullable=True))
    op.create_index("ix_lead_leads_trial_start", "lead_leads", ["trial_start"])


def downgrade() -> None:
    op.drop_index("ix_lead_leads_trial_start", table_name="lead_leads")
    for name in ("trial_last_visit", "trial_visits", "trial_payment_mode", "trial_paid_on", "trial_fee",
                 "trial_end", "trial_start"):
        op.drop_column("lead_leads", name)
    for column in reversed(_ORG):
        op.drop_column("org_organizations", column.name)
