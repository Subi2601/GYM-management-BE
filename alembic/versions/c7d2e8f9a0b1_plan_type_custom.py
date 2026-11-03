"""plan type CUSTOM: membership priced as days × per-day rate

Revision ID: c7d2e8f9a0b1
Revises: b3f1c2d4e5a6
Create Date: 2026-11-03 12:00:00

Adds the value to the native `plan_type` enum. The plan's `price` column keeps holding the total
(duration_days × per-day rate), so subscriptions, payments and invoices need no change.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c7d2e8f9a0b1"
down_revision: Union[str, None] = "b3f1c2d4e5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL 12+ allows ADD VALUE inside the migration transaction (it just can't be used in it).
    op.execute("ALTER TYPE plan_type ADD VALUE IF NOT EXISTS 'CUSTOM'")


def downgrade() -> None:
    # Enum values can't be dropped: custom plans become memberships, then the type is rebuilt without CUSTOM.
    op.execute("UPDATE plan_plans SET type = 'MEMBERSHIP' WHERE type = 'CUSTOM'")
    op.execute("ALTER TYPE plan_type RENAME TO plan_type_old")
    op.execute("CREATE TYPE plan_type AS ENUM ('MEMBERSHIP', 'ADD_ON')")
    op.execute("ALTER TABLE plan_plans ALTER COLUMN type DROP DEFAULT")
    op.execute("ALTER TABLE plan_plans ALTER COLUMN type TYPE plan_type USING type::text::plan_type")
    op.execute("ALTER TABLE plan_plans ALTER COLUMN type SET DEFAULT 'MEMBERSHIP'")
    op.execute("DROP TYPE plan_type_old")
