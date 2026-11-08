"""Plans, subscriptions and payments.

A payment covers 1..n subscriptions (multi-plan enrolment / renewal) via subscription.payment_id,
or exactly one PT subscription via payment.pt_subscription_id.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, SmallInteger, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PaymentMode, PlanServiceType, PlanType, SubscriptionStatus
from app.models.base import BaseModel, BranchScopedMixin


class PlanCategory(BaseModel):
    """Owner-managed plan groups (General, Student, Couple, Ladies only …) — one list for the whole organization.
    Only groups plans on screen; every rule (members, ID check, months …) lives on the plan."""
    __tablename__ = "plan_categories"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_organizations.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))


def default_upgrade_window(duration_months: int | None, duration_days: int | None) -> int:
    """Days after the start a member may still upgrade: 1 month → 15, ≤3 → 30, ≤6 → 45, longer → 60;
    plans billed by days → half the days. The owner can change it per plan."""
    if duration_months:
        return 15 if duration_months == 1 else 30 if duration_months <= 3 else 45 if duration_months <= 6 else 60
    return (duration_days or 0) // 2


def _upgrade_window_default(context) -> int:
    params = context.get_current_parameters()
    return default_upgrade_window(params.get("duration_months"), params.get("duration_days"))


class Plan(BranchScopedMixin, BaseModel):
    """A sellable plan. `is_active` (BaseModel) = shown for billing; hidden plans stay for history."""
    __tablename__ = "plan_plans"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_categories.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    # Calendar months (5 Nov + 3 → 5 Feb). NULL = bill by days (`duration_days`): PT validity, custom plans.
    duration_months: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Members one purchase covers (couple 2, family 3, friends 5 …); each gets their own membership.
    group_size: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default=text("1"))
    free_members: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    # Proof the desk must confirm before billing, e.g. "College ID card". NULL = none.
    id_check: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Members on this plan may check in at every branch of the organization.
    all_branches: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # Days after a subscription starts during which the member may upgrade to a bigger plan (0 = never).
    upgrade_window_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=_upgrade_window_default,
                                                     server_default=text("0"))
    # Cancelling gives money back only on refundable plans, within `refund_window_days` of use
    # (NULL = the gym's refund days from Gym settings).
    refundable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    refund_window_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
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
    # What an offer gave besides money off, as printed on the invoice: "Diwali: +1 month free, Protein shaker".
    offer_bonus: Mapped[str | None] = mapped_column(String(250), nullable=True)


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
    # Group plans: this member's share of the plan price (price ÷ members). NULL = the full plan price.
    price_share: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Renewal reminders sent for this subscription (Renewals screen); a renewal starts a new row, so they reset.
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # Upgrade: the old row ends on the upgrade day and points to the new one; the new row starts on the old
    # start date and records the credit (what the old plan cost) taken off its bill.
    upgraded_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="SET NULL"), nullable=True,
    )
    upgraded_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="SET NULL"), nullable=True,
    )
    upgrade_credit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Freeze: this member's own allowance in days (NULL = the gym's freeze days) and the days frozen so far
    # (already added to end_date).
    freeze_allowance_days: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    frozen_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    # Ended early: CANCELLED / TRANSFERRED (MembershipClose), the day and why. end_date is moved to the day before.
    closed_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    close_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Transfer: the old row points to the receiver's new row and back. A received membership can't move again.
    transferred_to_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="SET NULL"), nullable=True,
    )
    transferred_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="SET NULL"), nullable=True,
    )


class Offer(BranchScopedMixin, BaseModel):
    """Discount master (festival / referral offers). Billing screens offer only the active ones in their date
    window; the percentage is applied to the plans total. `is_active` (from BaseModel) is the on / off switch."""
    __tablename__ = "plan_offers"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Plan categories the % applies to (e.g. Diwali on General + Student). Empty = every plan.
    category_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False,
                                                          default=list, server_default=text("'{}'"))
    # Besides (or instead of) the %: extra membership time and / or a free item (supplement, T-shirt …).
    # Any mix; an offer needs at least one of %, extra time or free item.
    extra_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    extra_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    free_item: Mapped[str | None] = mapped_column(String(120), nullable=True)
