"""merge heads: employee UPI ID branch + SG member ID chain

The UPI ID migration was branched off the initial schema, leaving two heads, so a fresh database
(`alembic upgrade head`, e.g. the Docker deploy) refused to migrate. No schema change here.

Revision ID: b7c2e4f6a8d0
Revises: f7a1c9d2e3b5, a18f7d2c94b1
Create Date: 2026-11-21

"""
from typing import Sequence, Union

revision: str = "b7c2e4f6a8d0"
down_revision: Union[str, Sequence[str], None] = ("f7a1c9d2e3b5", "a18f7d2c94b1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
