"""roles per organization + role level (Owner > Sub-admin > Manager > Staff)

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-06 15:00:00

Schema only. `python -m app.utils.seed` then gives every organization its own Owner / Sub-admin / Manager / Staff
roles and moves existing logins from the old shared OWNER / ADMIN / TRAINER roles onto them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rbac_roles", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.add_column("rbac_roles", sa.Column("level", sa.SmallInteger(), server_default=sa.text("10"), nullable=False))
    op.create_index("ix_rbac_roles_organization_id", "rbac_roles", ["organization_id"])
    # Codes are unique per organization now (every gym has its own OWNER, MANAGER …).
    op.drop_index("ix_rbac_roles_code", table_name="rbac_roles")
    op.create_index("ix_rbac_roles_code", "rbac_roles", ["code"])
    op.create_unique_constraint("uq_rbac_roles_org_code", "rbac_roles", ["organization_id", "code"])
    op.execute("UPDATE rbac_roles SET level = 100 WHERE code = 'OWNER'")
    op.execute("UPDATE rbac_roles SET level = 50 WHERE code = 'ADMIN'")


def downgrade() -> None:
    op.drop_constraint("uq_rbac_roles_org_code", "rbac_roles", type_="unique")
    op.drop_index("ix_rbac_roles_code", table_name="rbac_roles")
    op.create_index("ix_rbac_roles_code", "rbac_roles", ["code"], unique=True)
    op.drop_index("ix_rbac_roles_organization_id", table_name="rbac_roles")
    op.drop_column("rbac_roles", "level")
    op.drop_column("rbac_roles", "organization_id")
