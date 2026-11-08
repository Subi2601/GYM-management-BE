"""plan categories (owner master), calendar months, group plans, ID check, all-branch plans, offer categories

Revision ID: a7b8c9d0e1f2
Revises: 6943b670b354
Create Date: 2026-11-06 10:00:00

Data: every organization gets the default categories; existing plans are filed by type (membership → General,
PT add-on → Personal Training, diet add-on → Diet, other add-ons → Add-ons, custom → Custom duration), and
membership plans of 30 / 90 / 180 / 360-365 days become 1 / 3 / 6 / 12 calendar months.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "6943b670b354"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_CATEGORIES = ["General", "Student - School", "Student - College", "Couple", "Family", "Friends",
                      "Corporate", "Personal Training", "Diet", "Add-ons", "Custom duration"]


def upgrade() -> None:
    op.create_table(
        "plan_categories",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_delete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["org_organizations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_categories_organization_id", "plan_categories", ["organization_id"])

    op.add_column("plan_plans", sa.Column("category_id", sa.UUID(), nullable=True))
    op.add_column("plan_plans", sa.Column("duration_months", sa.SmallInteger(), nullable=True))
    op.add_column("plan_plans", sa.Column("group_size", sa.SmallInteger(), server_default=sa.text("1"), nullable=False))
    op.add_column("plan_plans", sa.Column("free_members", sa.SmallInteger(), server_default=sa.text("0"), nullable=False))
    op.add_column("plan_plans", sa.Column("id_check", sa.String(length=60), nullable=True))
    op.add_column("plan_plans", sa.Column("all_branches", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("subscription_subscriptions", sa.Column("price_share", sa.Numeric(12, 2), nullable=True))
    op.add_column("plan_offers", sa.Column("category_ids", postgresql.ARRAY(sa.UUID()),
                                           server_default=sa.text("'{}'"), nullable=False))

    # Default categories for every organization.
    values = ", ".join(f"('{name}', {i})" for i, name in enumerate(DEFAULT_CATEGORIES, start=1))
    op.execute(f"""
        INSERT INTO plan_categories (organization_id, name, sort_order)
        SELECT o.id, d.name, d.sort_order FROM org_organizations o
        CROSS JOIN (VALUES {values}) AS d(name, sort_order)
    """)

    def file_plans(category: str, where: str) -> None:
        op.execute(f"""
            UPDATE plan_plans p SET category_id = c.id FROM plan_categories c
            WHERE c.organization_id = p.organization_id AND c.name = '{category}' AND p.category_id IS NULL
              AND ({where})
        """)

    file_plans("Custom duration", "p.type = 'CUSTOM'")
    file_plans("Personal Training", "p.type = 'ADD_ON' AND p.service_type = 'PERSONAL_TRAINING'")
    file_plans("Diet", "p.type = 'ADD_ON' AND p.service_type = 'DIET'")
    file_plans("Add-ons", "p.type = 'ADD_ON'")
    file_plans("General", "TRUE")

    op.execute("""
        UPDATE plan_plans SET duration_months = CASE duration_days
            WHEN 30 THEN 1 WHEN 90 THEN 3 WHEN 180 THEN 6 WHEN 360 THEN 12 WHEN 365 THEN 12 END
        WHERE type = 'MEMBERSHIP' AND duration_days IN (30, 90, 180, 360, 365)
    """)

    op.alter_column("plan_plans", "category_id", nullable=False)
    op.create_index("ix_plan_plans_category_id", "plan_plans", ["category_id"])
    op.create_foreign_key("fk_plan_plans_category_id", "plan_plans", "plan_categories", ["category_id"], ["id"],
                          ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_column("plan_offers", "category_ids")
    op.drop_column("subscription_subscriptions", "price_share")
    op.drop_constraint("fk_plan_plans_category_id", "plan_plans", type_="foreignkey")
    op.drop_index("ix_plan_plans_category_id", table_name="plan_plans")
    for col in ("all_branches", "id_check", "free_members", "group_size", "duration_months", "category_id"):
        op.drop_column("plan_plans", col)
    op.drop_index("ix_plan_categories_organization_id", table_name="plan_categories")
    op.drop_table("plan_categories")
