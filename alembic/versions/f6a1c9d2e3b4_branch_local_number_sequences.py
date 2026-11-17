"""Use branch-local member and receipt numbers.

Revision ID: f6a1c9d2e3b4
Revises: ce1a60a05206
Create Date: 2026-11-17
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f6a1c9d2e3b4"
down_revision: Union[str, Sequence[str], None] = "ce1a60a05206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_member_members_org_reg", "member_members", type_="unique")
    op.create_unique_constraint(
        "uq_member_members_branch_reg", "member_members", ["branch_id", "registration_id"])
    op.drop_constraint("uq_payment_payments_org_receipt", "payment_payments", type_="unique")
    op.create_unique_constraint(
        "uq_payment_payments_branch_receipt", "payment_payments", ["branch_id", "receipt_no"])


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_member_members_org_reg", "member_members", ["organization_id", "registration_id"])
    op.create_unique_constraint(
        "uq_payment_payments_org_receipt", "payment_payments", ["organization_id", "receipt_no"])
    op.drop_constraint("uq_member_members_branch_reg", "member_members", type_="unique")
    op.drop_constraint("uq_payment_payments_branch_receipt", "payment_payments", type_="unique")
