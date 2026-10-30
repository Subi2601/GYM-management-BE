"""Pydantic v2 schemas — payments, collection stats, invoice."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import PaymentMode, PlanServiceType, PlanType
from app.schemas.common import FormSchema


class PaymentCreate(FormSchema):
    """Pay existing unpaid subscriptions (same member) OR one PT subscription — exactly one target."""
    subscription_ids: list[UUID] | None = Field(default=None, max_length=20)
    pt_subscription_id: UUID | None = None
    discount_amount: float | None = Field(default=None, ge=0)   # None → discounts stored on the subscriptions
    discount_reason: str | None = Field(default=None, max_length=200)
    paid_amount: float = Field(ge=0)
    payment_mode: PaymentMode
    balance_due_date: date | None = None
    payment_date: date | None = None

    @field_validator("subscription_ids")
    @classmethod
    def _distinct(cls, v: list[UUID] | None) -> list[UUID] | None:
        if v is not None and len(set(v)) != len(v):
            raise ValueError("subscription_ids must be distinct")
        return v or None

    @model_validator(mode="after")
    def _one_target(self) -> "PaymentCreate":
        if bool(self.subscription_ids) == (self.pt_subscription_id is not None):
            raise ValueError("Provide either subscription_ids or pt_subscription_id (exactly one)")
        return self


class PaymentResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    receipt_no: str
    member_id: UUID
    member_name: str
    registration_id: str
    member_phone: str
    plan_names: list[str]
    pt_subscription_id: UUID | None = None
    amount: float
    discount_amount: float
    discount_reason: str | None = None
    paid_amount: float
    balance_amount: float
    balance_due_date: date | None = None
    payment_date: date
    payment_mode: PaymentMode


class PaymentStats(TessBaseSchema):
    today: float
    today_cash: float
    today_account: float          # every non-cash mode (UPI, card, bank transfer)
    this_month: float
    last_month: float
    last_6_months: float
    last_12_months: float
    total: float


class InvoiceMember(TessBaseSchema):
    id: UUID
    registration_id: str
    name: str
    phone: str


class InvoiceLine(TessBaseSchema):
    plan_name: str
    plan_type: PlanType | None = None
    service_type: PlanServiceType | None = None
    duration_days: int | None = None
    total_sessions: int
    start_date: date
    end_date: date
    price: float


class InvoiceResponse(TessBaseSchema):
    payment_id: UUID
    receipt_no: str
    payment_date: date
    payment_mode: PaymentMode
    organization_name: str
    branch_name: str
    branch_location: str | None = None
    member: InvoiceMember
    lines: list[InvoiceLine]
    gross: float
    discount_amount: float
    discount_reason: str | None = None
    net_amount: float
    paid_amount: float
    balance_amount: float
    balance_due_date: date | None = None
