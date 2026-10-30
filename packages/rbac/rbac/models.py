"""
RBAC SQLAlchemy models — shared package.
Fully dynamic — all values created at runtime, no hardcoded enums.
Single-tenant: one role set, no tenant scoping.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models.base_model import BaseModel


class RBACModule(BaseModel):
    """Top-level feature groups — Level 1 of Module → Screen → Permission."""
    __tablename__ = "rbac_modules"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))

    screens: Mapped[list["RBACScreen"]] = relationship(back_populates="module", lazy="select")


class RBACScreen(BaseModel):
    """Individual UI pages within a module — Level 2."""
    __tablename__ = "rbac_screens"

    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rbac_modules.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    route_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))

    module: Mapped["RBACModule"] = relationship(back_populates="screens")
    permissions: Mapped[list["RBACPermission"]] = relationship(back_populates="screen", lazy="select")


class RBACPermission(BaseModel):
    """Atomic action privileges on a screen — Level 3."""
    __tablename__ = "rbac_permissions"

    screen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rbac_screens.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    screen: Mapped["RBACScreen"] = relationship(back_populates="permissions")


class RBACRole(BaseModel):
    """
    Operator role definition (e.g. ADMIN, CONTROLLER, OPERATOR, AUDITOR).
    is_system=true roles cannot be deleted or deactivated.
    """
    __tablename__ = "rbac_roles"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class RBACRolePermission(BaseModel):
    """
    Core RBAC grant table.
    screen_id is denormalised here to avoid a join on the hot permission-check path.
    is_granted=false = explicit deny. Deny wins when user holds multiple roles.
    """
    __tablename__ = "rbac_role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "screen_id", "permission_id", name="uq_role_screen_permission"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rbac_roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Denormalised for fast permission checks — avoids join on every API call
    screen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rbac_screens.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rbac_permissions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # true = grant | false = explicit deny. Deny wins over grant on multiple roles.
    is_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class UserRole(BaseModel):
    """Assigns a role to a user."""
    __tablename__ = "rbac_user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rbac_roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
