"""Pydantic v2 schemas — members."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import EmailStr, Field
from shared.schemas.base_schema import TimestampMixin, UUIDSchema

from app.core.enums import Gender, MemberStatus, MembershipState
from app.schemas.common import FormSchema, Phone


class MemberCreate(FormSchema):
    name: str = Field(min_length=1, max_length=120)
    phone: Phone
    email: EmailStr | None = None
    gender: Gender = Gender.MALE
    dob: date | None = None
    address: str | None = Field(default=None, max_length=300)
    blood_group: str | None = Field(default=None, max_length=5)
    weight: float | None = Field(default=None, gt=0, le=400)
    height: float | None = Field(default=None, gt=0, le=300)
    fitness_goal: str | None = Field(default=None, max_length=200)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: Phone | None = None
    joining_date: date | None = None          # defaults to today
    id_proof_type: str | None = Field(default=None, max_length=40)
    id_proof_number: str | None = Field(default=None, max_length=40)
    status: MemberStatus = MemberStatus.ACTIVE


class MemberUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: Phone | None = None
    email: EmailStr | None = None
    gender: Gender | None = None
    dob: date | None = None
    address: str | None = Field(default=None, max_length=300)
    blood_group: str | None = Field(default=None, max_length=5)
    weight: float | None = Field(default=None, gt=0, le=400)
    height: float | None = Field(default=None, gt=0, le=300)
    fitness_goal: str | None = Field(default=None, max_length=200)
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: Phone | None = None
    joining_date: date | None = None
    id_proof_type: str | None = Field(default=None, max_length=40)
    id_proof_number: str | None = Field(default=None, max_length=40)
    status: MemberStatus | None = None


class MemberResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    registration_id: str
    name: str
    phone: str
    email: str | None = None
    gender: Gender
    dob: date | None = None
    address: str | None = None
    blood_group: str | None = None
    weight: float | None = None
    height: float | None = None
    fitness_goal: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    joining_date: date
    id_proof_type: str | None = None
    id_proof_number: str | None = None   # decrypted for pii:view, masked otherwise
    status: MemberStatus
    # Derived from the latest MEMBERSHIP subscription
    membership_state: MembershipState
    current_plan_id: UUID | None = None
    current_plan_name: str | None = None
    expiry_date: date | None = None


class MemberCounts(FormSchema):
    total: int
    active: int
