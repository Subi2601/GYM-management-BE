"""Pydantic schemas for RBAC management API — full CRUD."""
from __future__ import annotations

from uuid import UUID

from pydantic import Field

from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema


# ── Module ────────────────────────────────────────────────────────────────────

class ModuleCreate(TessBaseSchema):
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=100)
    icon: str | None = Field(default=None, max_length=100)
    sort_order: int = 0


class ModuleUpdate(TessBaseSchema):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    icon: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ModuleResponse(UUIDSchema, TimestampMixin):
    name: str
    code: str
    icon: str | None
    sort_order: int
    is_active: bool


# ── Screen ────────────────────────────────────────────────────────────────────

class ScreenCreate(TessBaseSchema):
    module_id: UUID
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=100)
    route_path: str | None = Field(default=None, max_length=255)
    sort_order: int = 0


class ScreenUpdate(TessBaseSchema):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    route_path: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ScreenResponse(UUIDSchema, TimestampMixin):
    module_id: UUID
    name: str
    code: str
    route_path: str | None
    sort_order: int
    is_active: bool


# ── Permission ────────────────────────────────────────────────────────────────

class PermissionCreate(TessBaseSchema):
    screen_id: UUID
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class PermissionUpdate(TessBaseSchema):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    code: str | None = Field(default=None, min_length=2, max_length=100)
    is_active: bool | None = None


class PermissionResponse(UUIDSchema, TimestampMixin):
    screen_id: UUID
    name: str
    code: str
    description: str | None
    is_active: bool


# ── Role ──────────────────────────────────────────────────────────────────────

class RoleCreate(TessBaseSchema):
    name: str = Field(min_length=2, max_length=100)
    code: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=1, max_length=500)


class RoleUpdate(TessBaseSchema):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None


class RoleResponse(UUIDSchema, TimestampMixin):
    name: str
    code: str
    description: str | None
    is_system: bool
    is_active: bool


# ── Role Permissions ──────────────────────────────────────────────────────────

class RolePermissionGrant(TessBaseSchema):
    permission_id: UUID
    screen_id: UUID
    is_granted: bool = True


class AssignPermissionsRequest(TessBaseSchema):
    grants: list[RolePermissionGrant]


class AssignPermissionsLegacy(TessBaseSchema):
    """Backward-compat — simple list of permission_ids (all granted=true)."""
    permission_ids: list[UUID]


# ── User Role ─────────────────────────────────────────────────────────────────

class AssignRoleRequest(TessBaseSchema):
    role_id: UUID


class UserRoleResponse(UUIDSchema):
    user_id: UUID
    role_id: UUID
    assigned_by: UUID
    is_active: bool
