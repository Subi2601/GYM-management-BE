"""plan upgrades: per-plan upgrade window, subscription upgrade links + credit

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-06 12:00:00

Data: existing plans get the default window — 1 month → 15 days, up to 3 months → 30, up to 6 → 45,
longer → 60; plans billed by days → half their days.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("plan_plans", sa.Column("upgrade_window_days", sa.SmallInteger(), server_default=sa.text("0"),
                                          nullable=False))
    op.execute("""
        UPDATE plan_plans SET upgrade_window_days = CASE
            WHEN duration_months = 1 THEN 15
            WHEN duration_months <= 3 THEN 30
            WHEN duration_months <= 6 THEN 45
            WHEN duration_months > 6 THEN 60
            ELSE duration_days / 2 END
    """)
    op.add_column("subscription_subscriptions", sa.Column("upgraded_to_id", sa.UUID(), nullable=True))
    op.add_column("subscription_subscriptions", sa.Column("upgraded_from_id", sa.UUID(), nullable=True))
    op.add_column("subscription_subscriptions", sa.Column("upgrade_credit", sa.Numeric(12, 2), nullable=True))
    op.create_foreign_key("fk_subscription_subscriptions_upgraded_to_id", "subscription_subscriptions",
                          "subscription_subscriptions", ["upgraded_to_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_subscription_subscriptions_upgraded_from_id", "subscription_subscriptions",
                          "subscription_subscriptions", ["upgraded_from_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_subscription_subscriptions_upgraded_from_id", "subscription_subscriptions",
                       type_="foreignkey")
    op.drop_constraint("fk_subscription_subscriptions_upgraded_to_id", "subscription_subscriptions",
                       type_="foreignkey")
    op.drop_column("subscription_subscriptions", "upgrade_credit")
    op.drop_column("subscription_subscriptions", "upgraded_from_id")
    op.drop_column("subscription_subscriptions", "upgraded_to_id")
    op.drop_column("plan_plans", "upgrade_window_days")
