"""Pydantic v2 schemas — subscriptions (renewal board, history, enrolment)."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import (PaymentMode, PaymentStatus, PlanServiceType, PlanType, RenewalState,
                            SubscriptionStatus)
from app.schemas.common import FormSchema, Phone


class EnrollPayment(FormSchema):
    discount_amount: float = Field(default=0, ge=0)
    discount_reason: str | None = Field(default=None, max_length=200)
    # An offer from the master: when set, the discount is its % of the plans total and the reason its name
    # (discount_amount / discount_reason are then ignored).
    offer_id: UUID | None = None
    paid_amount: float = Field(ge=0)
    payment_mode: PaymentMode
    balance_due_date: date | None = None
    payment_date: date | None = None          # defaults to today


class GroupMember(FormSchema):
    """Another member on a group package: an existing member, or a new one (name + phone) created on the spot."""
    member_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: Phone | None = None

    @model_validator(mode="after")
    def _one_way(self) -> "GroupMember":
        if self.member_id is None and not (self.name and self.phone):
            raise ValueError("pick an existing member or give a name and phone")
        return self


class EnrollRequest(FormSchema):
    """Atomic multi-plan enrolment / renewal: subscriptions + payment (+ PT records) in one transaction.
    A group package (couple, family …) also takes the other members — each gets their own membership."""
    member_id: UUID                           # the payer
    plan_ids: list[UUID] = Field(min_length=1, max_length=20)
    start_date: date | None = None            # defaults to today
    trainer_id: UUID | None = None            # for PERSONAL_TRAINING plans
    group_members: list[GroupMember] = Field(default_factory=list, max_length=49)
    id_verified: bool = False                 # desk confirmed the plan's ID check (student ID …)
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


class UpgradeRequest(FormSchema):
    """Move the member's current membership up to a bigger plan inside its upgrade window: the new plan starts on
    the old start date and the old plan's cost is credited, so only the balance is billed."""
    member_id: UUID
    plan_id: UUID
    id_verified: bool = False
    payment: EnrollPayment


class UpgradeOption(TessBaseSchema):
    """One membership plan in the upgrade list: bigger ones can be picked, the rest show why not."""
    plan_id: UUID
    name: str
    category_id: UUID
    category_name: str
    duration_months: int | None = None
    duration_days: int
    price: float
    id_check: str | None = None
    eligible: bool
    reason: str | None = None                 # why it can't be picked (lower price, shorter, current …)
    balance: float                            # price − credit (what the member pays before any offer)


class UpgradeCurrent(TessBaseSchema):
    subscription_id: UUID
    plan_id: UUID
    plan_name: str
    category_name: str
    start_date: date
    end_date: date
    credit: float                             # what the current plan cost (after its discount)
    receipt_no: str | None = None
    window_days: int
    window_ends: date | None = None           # last day to upgrade; None = upgrades off for this plan


class UpgradeInfo(TessBaseSchema):
    """GET /subscriptions/member/{id}/upgrade — whether the member can upgrade now, and the plan list."""
    current: UpgradeCurrent | None = None
    can_upgrade: bool
    reason: str | None = None                 # why not (window closed, balance pending, no plan …)
    options: list[UpgradeOption]


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
    upgraded_to_id: UUID | None = None        # this plan was upgraded (to that subscription)
    upgraded_from_id: UUID | None = None      # this plan is an upgrade of that subscription
    upgrade_credit: float | None = None       # credit taken off this plan's bill for the old one
    frozen_days: int = 0                      # freeze days already added to end_date
    closed_reason: str | None = None          # CANCELLED / TRANSFERRED (ended early)
    closed_on: date | None = None
    close_note: str | None = None             # who it went to / refund, and why
    transferred_to_id: UUID | None = None
    transferred_from_id: UUID | None = None   # received from another member (paid by them)


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
