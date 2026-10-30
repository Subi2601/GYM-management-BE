"""Pydantic v2 schemas — leads."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TimestampMixin, UUIDSchema

from app.core.enums import LeadStatus
from app.schemas.common import FormSchema, Phone


class LeadCreate(FormSchema):
    name: str = Field(min_length=1, max_length=120)
    phone: Phone
    location: str = Field(min_length=1, max_length=150)
    goal: str = Field(min_length=1, max_length=150)
    status: LeadStatus
    plan_to_join_date: date
    next_follow_up_date: date
    notes: str | None = Field(default=None, max_length=5000)


class LeadUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: Phone | None = None
    location: str | None = Field(default=None, min_length=1, max_length=150)
    goal: str | None = Field(default=None, min_length=1, max_length=150)
    status: LeadStatus | None = None
    plan_to_join_date: date | None = None
    next_follow_up_date: date | None = None
    notes: str | None = Field(default=None, max_length=5000)


class LeadFollowUp(FormSchema):
    notes: str = Field(min_length=1, max_length=1000)
    next_follow_up_date: date | None = None
    status: LeadStatus | None = None          # defaults to FOLLOW_UP


class LeadResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    name: str
    phone: str
    location: str | None = None
    goal: str | None = None
    status: LeadStatus
    plan_to_join_date: date | None = None
    next_follow_up_date: date | None = None
    last_follow_up_date: date | None = None
    notes: str | None = None
    converted_member_id: UUID | None = None


class LeadConvertResponse(LeadResponse):
    member_id: UUID
    registration_id: str
