"""Pydantic v2 schemas — leads."""
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import FitnessGoal, LeadSource, LeadStatus, PaymentMode
from app.schemas.common import FormSchema, Phone

# Derived from the trial dates: booked for later / running today / over.
TrialState = Literal["UPCOMING", "ON", "ENDED"]


class LeadCreate(FormSchema):
    name: str = Field(min_length=1, max_length=120)
    phone: Phone
    location: str = Field(min_length=1, max_length=150)
    goal: FitnessGoal
    source: LeadSource
    status: LeadStatus
    plan_to_join_date: date
    next_follow_up_date: date
    notes: str | None = Field(default=None, max_length=5000)
    referred_by_id: UUID | None = None        # source REFERRAL: the member who sent them


class LeadUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: Phone | None = None
    location: str | None = Field(default=None, min_length=1, max_length=150)
    goal: FitnessGoal | None = None
    source: LeadSource | None = None
    status: LeadStatus | None = None
    plan_to_join_date: date | None = None
    next_follow_up_date: date | None = None
    notes: str | None = Field(default=None, max_length=5000)
    referred_by_id: UUID | None = None


class LeadFollowUp(FormSchema):
    notes: str = Field(min_length=1, max_length=1000)
    next_follow_up_date: date | None = None
    status: LeadStatus | None = None          # defaults to FOLLOW_UP


class LeadResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    name: str
    phone: str
    location: str | None = None
    goal: FitnessGoal | None = None
    source: LeadSource | None = None          # None = not recorded (older leads)
    status: LeadStatus
    plan_to_join_date: date | None = None
    next_follow_up_date: date | None = None
    last_follow_up_date: date | None = None
    notes: str | None = None
    converted_member_id: UUID | None = None
    # The account that took the enquiry (whoever was logged in when the lead was added).
    attended_by_id: UUID | None = None
    attended_by_name: str | None = None
    referred_by_id: UUID | None = None
    referred_by_name: str | None = None
    # Trial class (None = no trial booked).
    trial_start: date | None = None
    trial_end: date | None = None
    trial_state: TrialState | None = None
    trial_fee: float | None = None            # 0 = free
    trial_paid_on: date | None = None
    trial_payment_mode: PaymentMode | None = None
    trial_visits: int = 0
    trial_last_visit: date | None = None


class LeadTrialStart(FormSchema):
    start_date: date


class LeadTrialPaid(FormSchema):
    payment_mode: PaymentMode


class LeadAttendant(TessBaseSchema):
    """An account that has taken enquiries in the branch (the "Attended by" filter)."""
    id: UUID
    name: str


class LeadCounts(TessBaseSchema):
    """Row count per list tab (GET /leads/counts) — same rules as `filter`."""
    all: int
    followup: int
    trial: int
    rejected: int


class LeadConvertResponse(LeadResponse):
    member_id: UUID
    registration_id: str
