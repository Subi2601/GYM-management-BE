from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseModel(Base):
    """
    Abstract base for all ORM models.
    Provides: UUID PK, standard audit columns, UTC timestamps, soft delete.

    Every table inherits:
        id, is_active, is_delete,
        created_by, updated_by, deleted_by,
        created_at, updated_at, deleted_at

    Models that need a FK on created_by / updated_by can redefine
    the column in the concrete class — SQLAlchemy replaces the abstract
    definition with the subclass definition.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        sort_order=-10,   # always first column in every table
    )

    # ── Audit flags ──────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"), sort_order=90,
    )
    is_delete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), sort_order=91,
    )

    # ── Audit actors ─────────────────────────────────────────────
    # Plain UUID — no FK (creator can be any user type across tables).
    # Concrete models that need a FK constraint should redefine the column.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, sort_order=92,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, sort_order=93,
    )
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, sort_order=94,
    )

    # ── Timestamps ───────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=utcnow,
        sort_order=100,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=utcnow,
        default=utcnow,
        sort_order=101,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        sort_order=102,
    )

    def soft_delete(self, deleted_by: uuid.UUID | None = None) -> None:
        """Mark record as deleted. Sets deleted_at, is_delete=True, and optionally deleted_by."""
        self.deleted_at = utcnow()
        self.is_delete = True
        if deleted_by:
            self.deleted_by = deleted_by

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
