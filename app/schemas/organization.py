"""Pydantic v2 schemas — organizations (SaaS onboarding) and branches."""
from __future__ import annotations

from uuid import UUID

from pydantic import EmailStr, Field, field_validator
from shared.schemas.base_schema import TimestampMixin, UUIDSchema

from app.schemas.common import FormSchema, Phone


# ── branches ─────────────────────────────────────────────────────────────
class _BranchContacts(FormSchema):
    """Branch phone / email (not unique: the head office often uses the gym's main number), GSTIN override."""
    phone: str | None = Field(default=None, max_length=60)
    email: EmailStr | None = None
    gstin: str | None = None
    is_head_office: bool | None = None

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        from app.schemas.gym_profile import check_gstin
        return check_gstin(v)


class BranchCreate(_BranchContacts):
    branch_name: str = Field(min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    login_email: EmailStr
    login_password: str = Field(min_length=6, max_length=128)


class BranchUpdate(_BranchContacts):
    branch_name: str | None = Field(default=None, min_length=1, max_length=120)
    location: str | None = Field(default=None, max_length=200)


class BranchPasswordReset(FormSchema):
    new_password: str = Field(min_length=6, max_length=128)


class BranchResponse(UUIDSchema, TimestampMixin):
    organization_id: UUID
    branch_name: str
    location: str | None = None
    login_email: str | None = None   # the branch OWNER login (password is never exposed)
    phone: str | None = None
    email: str | None = None
    gstin: str | None = None         # None = the gym's GSTIN
    is_head_office: bool = False
    members_count: int = 0
    staff_count: int = 0


# ── organizations ────────────────────────────────────────────────────────
class OrganizationCreate(FormSchema):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{2,40}$", description="Unique tenant code, e.g. STAG")
    contact_email: EmailStr | None = None
    contact_phone: Phone | None = None
    branch_name: str = Field(min_length=1, max_length=120)
    branch_location: str | None = Field(default=None, max_length=200)
    owner_name: str = Field(min_length=1, max_length=120)
    owner_email: EmailStr
    owner_password: str = Field(min_length=6, max_length=128)


class OrganizationResponse(UUIDSchema, TimestampMixin):
    name: str
    code: str
    contact_email: str | None = None
    contact_phone: str | None = None
    is_active: bool
    branch_count: int = 0


class OrganizationOnboardResponse(OrganizationResponse):
    branch_id: UUID
    branch_name: str
    owner_user_id: UUID
    owner_email: str
