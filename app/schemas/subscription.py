"""Pydantic v2 schemas — subscriptions (renewal board, history, enrolment)."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field, field_validator
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import (PaymentMode, PaymentStatus, PlanServiceType, PlanType, RenewalState,
                            SubscriptionStatus)
from app.schemas.common import FormSchema


class EnrollPayment(FormSchema):
    discount_amount: float = Field(default=0, ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)
    paid_amount: float = Field(ge=0)
    payment_mode: PaymentMode
    balance_due_date: date | None = None
    payment_date: date | None = None          # defaults to today


class EnrollRequest(FormSchema):
    """Atomic multi-plan enrolment / renewal: subscriptions + payment (+ PT records) in one transaction."""
    member_id: UUID
    plan_ids: list[UUID] = Field(min_length=1, max_length=20)
    start_date: date | None = None            # defaults to today
    trainer_id: UUID | None = None            # for PERSONAL_TRAINING plans
    payment: EnrollPayment

    @field_validator("plan_ids")
    @classmethod
    def _distinct(cls, v: list[UUID]) -> list[UUID]:
        if len(set(v)) != len(v):
            raise ValueError("plan_ids must be distinct")
        return v


class EnrollResponse(TessBaseSchema):
    payment_id: UUID
    receipt_no: str
    subscription_ids: list[UUID]
    pt_subscription_ids: list[UUID]
    amount: float
    discount_amount: float
    paid_amount: float
    balance_amount: float


class SubscriptionCreate(FormSchema):
    """Single unpaid subscription (paid later through POST /payments)."""
    member_id: UUID
    plan_id: UUID
    start_date: date | None = None
    discount_amount: float = Field(default=0, ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)
    trainer_id: UUID | None = None


class SubscriptionResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    member_id: UUID
    member_name: str
    registration_id: str
    member_phone: str
    plan_id: UUID
    plan_name: str
    plan_type: PlanType
    service_type: PlanServiceType
    price: float
    start_date: date
    end_date: date
    discount_amount: float
    discount_reason: str | None = None
    status: SubscriptionStatus
    payment_id: UUID | None = None
    payment_status: PaymentStatus
    renewal_state: RenewalState
    days_left: int                            # negative = days since expiry


class SubscriptionPlanLine(TessBaseSchema):
    subscription_id: UUID
    plan_id: UUID
    plan_name: str
    plan_type: PlanType
    service_type: PlanServiceType
    duration_days: int
    total_sessions: int
    start_date: date
    end_date: date
    price: float


class SubscriptionMember(TessBaseSchema):
    id: UUID
    registration_id: str
    name: str
    phone: str


class SubscriptionPaymentSummary(TessBaseSchema):
    id: UUID
    receipt_no: str
    payment_date: date
    payment_mode: PaymentMode
    amount: float
    discount_amount: float
    paid_amount: float
    balance_amount: float
    balance_due_date: date | None = None


class SubscriptionDetail(SubscriptionResponse):
    member: SubscriptionMember
    plans: list[SubscriptionPlanLine]         # every plan billed together (same payment), or just this one
    payment: SubscriptionPaymentSummary | None = None
    pt_subscription_id: UUID | None = None


class SubscriptionCounts(TessBaseSchema):
    """Row count per board tab (GET /subscriptions/counts); `active` = renewal_state NONE."""
    all: int
    expiring: int
    expired: int
    active: int
