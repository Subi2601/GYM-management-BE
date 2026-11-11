"""branch name unique live only

Revision ID: ce1a60a05206
Revises: e5a7c9d1f3b4
Create Date: 2026-11-10 15:08:46.060396

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce1a60a05206'
down_revision: Union[str, None] = 'e5a7c9d1f3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_org_branches_org_name", "org_branches", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_org_branches_org_name_live "
        "ON org_branches (organization_id, lower(branch_name)) WHERE is_delete = false"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_org_branches_org_name_live")
    op.create_unique_constraint("uq_org_branches_org_name", "org_branches", ["organization_id", "branch_name"])
