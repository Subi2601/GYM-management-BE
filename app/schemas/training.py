"""Pydantic v2 schemas — personal training subscriptions and session logs."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import FitnessGoal, PTStatus
from app.schemas.common import FormSchema


class PTSubscribeRequest(FormSchema):
    member_id: UUID
    trainer_id: UUID
    plan_id: UUID                             # must be a PERSONAL_TRAINING plan
    start_date: date | None = None            # defaults to today
    goal: FitnessGoal | None = None


class PTTrainerUpdate(FormSchema):
    trainer_id: UUID


class PTSessionLogCreate(FormSchema):
    session_date: date | None = None          # defaults to today
    trainer_id: UUID | None = None            # optional trainer change while logging
    trainer_verified: bool = False
    client_verified: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class PTSubscriptionResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    member_id: UUID
    member_name: str
    registration_id: str
    member_phone: str
    trainer_id: UUID | None = None
    trainer_name: str                         # "Not Assigned" when empty
    plan_id: UUID | None = None
    plan_name: str
    subscription_id: UUID | None = None
    goal: FitnessGoal | None = None
    total_sessions: int
    sessions_remaining: int
    sessions_used: int
    start_date: date
    expiry_date: date
    is_paid: bool
    status: PTStatus


class PTSessionLogResponse(UUIDSchema, TimestampMixin):
    pt_subscription_id: UUID
    session_date: date
    trainer_id: UUID | None = None
    trainer_name: str
    trainer_verified: bool
    client_verified: bool
    notes: str | None = None
    sessions_remaining_after: int


class PTCounts(TessBaseSchema):
    """Row count per list tab (GET /personal-training/counts) — same rules as `status` / `paid_only`."""
    active: int
    completed: int
    expired: int
    all: int
