# Re-exports the shared declarative base + abstract BaseModel so every model
# (and the rbac package models) share one metadata for Alembic.
# BaseModel provides: UUID PK, is_active, is_delete, created_by/updated_by/deleted_by,
# created_at/updated_at/deleted_at (UTC), soft_delete().
import uuid

from shared.database.base import Base
from shared.models.base_model import BaseModel, utcnow
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class BranchScopedMixin:
    """Tenant + branch ownership columns carried by every business row (SaaS boundary)."""

    @declared_attr
    def organization_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("org_organizations.id", ondelete="RESTRICT"),
                             nullable=False, index=True, sort_order=-9)

    @declared_attr
    def branch_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("org_branches.id", ondelete="RESTRICT"),
                             nullable=False, index=True, sort_order=-8)


__all__ = ["Base", "BaseModel", "BranchScopedMixin", "utcnow"]
