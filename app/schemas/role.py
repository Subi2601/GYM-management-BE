"""Pydantic v2 schemas — roles & access."""
from __future__ import annotations

from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema

from app.schemas.common import FormSchema


class RoleCreate(FormSchema):
    name: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    # 80 = all branches (like Sub-admin), 50 = branch manager, 10 = branch staff.
    level: int
    # Start from this role's ticks; default = the built-in role of the same level.
    copy_from_id: UUID | None = None


class RoleUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    level: int | None = None                  # own roles only


class RolePermissionsUpdate(FormSchema):
    """The role's full access: every permission code it should have (others are removed)."""
    codes: list[str] = Field(default_factory=list, max_length=500)


class RoleResponse(TessBaseSchema):
    id: UUID
    code: str
    name: str
    description: str | None = None
    level: int
    level_label: str                          # Owner / All branches / Branch manager / Branch staff
    all_branches: bool                        # sees every branch (can switch)
    is_system: bool                           # built-in: can't be deleted
    is_owner: bool                            # always full access, not editable
    user_count: int
    permission_count: int
    editable: bool                            # below the caller's level (and not Owner)


class RoleDetail(RoleResponse):
    permissions: list[str]


class CatalogPermission(TessBaseSchema):
    code: str
    name: str
    owner_only: bool                          # can't be given to any other role
    all_branches_only: bool                   # only for All branches roles


class CatalogScreen(TessBaseSchema):
    code: str
    name: str
    permissions: list[CatalogPermission]


class CatalogModule(TessBaseSchema):
    code: str
    name: str
    icon: str | None = None
    screens: list[CatalogScreen]
