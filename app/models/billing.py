"""Plans, subscriptions and payments.

A payment covers 1..n subscriptions (multi-plan enrolment / renewal) via subscription.payment_id,
or exactly one PT subscription via payment.pt_subscription_id.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PaymentMode, PlanServiceType, PlanType, SubscriptionStatus
from app.models.base import BaseModel, BranchScopedMixin


class Plan(BranchScopedMixin, BaseModel):
    __tablename__ = "plan_plans"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[PlanType] = mapped_column(
        Enum(PlanType, name="plan_type"), nullable=False,
        default=PlanType.MEMBERSHIP, server_default=text("'MEMBERSHIP'"),
    )
    service_type: Mapped[PlanServiceType] = mapped_column(
        Enum(PlanServiceType, name="plan_service_type"), nullable=False,
        default=PlanServiceType.GENERAL, server_default=text("'GENERAL'"),
    )
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Payment(BranchScopedMixin, BaseModel):
    __tablename__ = "payment_payments"
    __table_args__ = (
        UniqueConstraint("organization_id", "receipt_no", name="uq_payment_payments_org_receipt"),
    )

    receipt_no: Mapped[str] = mapped_column(String(20), nullable=False)  # REC-0001
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    # use_alter: payment ↔ subscription ↔ pt_subscription form an FK cycle; this edge is added after CREATE.
    pt_subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pt_subscriptions.id", ondelete="RESTRICT", use_alter=True,
                   name="fk_payment_payments_pt_subscription_id"),
        nullable=True, index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)          # gross (plan prices)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0,
                                                     server_default=text("0"))
    discount_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0,
                                                    server_default=text("0"))
    balance_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode, name="payment_mode"), nullable=False)


class Subscription(BranchScopedMixin, BaseModel):
    __tablename__ = "subscription_subscriptions"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_plans.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payment_payments.id", ondelete="SET NULL", use_alter=True,
                   name="fk_subscription_subscriptions_payment_id"),
        nullable=True, index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0,
                                                     server_default=text("0"))
    discount_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"), nullable=False,
        default=SubscriptionStatus.ACTIVE, server_default=text("'ACTIVE'"),
    )
