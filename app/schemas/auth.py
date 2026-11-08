"""Pydantic v2 schemas — auth."""
from __future__ import annotations

from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema

from app.core.enums import AccountRole


class LoginRequest(TessBaseSchema):
    # Plain string: login only looks the account up, and EmailStr rejects reserved
    # domains such as `.local` used by on-prem / platform accounts.
    email: str = Field(min_length=3, max_length=150)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(TessBaseSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ChangePasswordRequest(TessBaseSchema):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class PermissionItem(TessBaseSchema):
    id: str
    name: str
    code: str


class ScreenAccess(TessBaseSchema):
    screen_id: str
    screen_name: str
    screen_code: str
    screen_route: str | None = None
    permissions: list[PermissionItem]


class ModuleAccess(TessBaseSchema):
    module_id: str
    module_name: str
    module_code: str
    module_icon: str | None = None
    sort_order: int
    screens: list[ScreenAccess]


class BranchBrief(TessBaseSchema):
    id: UUID
    branch_name: str
    location: str | None = None


class MeUser(TessBaseSchema):
    id: UUID
    name: str
    email: str
    role: AccountRole
    role_name: str | None = None              # the gym role (Owner, Sub-admin, Manager, Staff or the gym's own)
    role_level: int | None = None
    is_superadmin: bool
    organization_id: UUID | None = None
    organization_name: str | None = None
    organization_code: str | None = None      # Gym ID
    organization_logo_url: str | None = None  # public logo (Gym Settings)
    branch_id: UUID | None = None


class MeResponse(TessBaseSchema):
    user: MeUser
    roles: list[str]
    permissions: list[str]
    access: list[ModuleAccess]
    branches: list[BranchBrief]
    can_switch_branch: bool
