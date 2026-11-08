"""Membership actions — freezes, refunds, the proof documents behind them — and client assessments."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (Date, Enum, Float, ForeignKey, Integer, LargeBinary, Numeric, SmallInteger, String, Text,
                        UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PaymentMode
from app.models.base import BaseModel, BranchScopedMixin


class MemberDocument(BranchScopedMixin, BaseModel):
    """A file the desk attached as proof (medical note, letter …). Kept in the database (small files only), so
    hosting needs no file storage. `kind` = DocumentKind."""
    __tablename__ = "member_documents"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    # The membership the action was on (transfer / cancel proof is found through it).
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class SubscriptionFreeze(BranchScopedMixin, BaseModel):
    """One freeze of a membership: frozen from `start_date` to `end_date` (both included). The days were added to
    the membership's end when it was frozen; resuming early (`resumed_on`) gives the unused days back."""
    __tablename__ = "subscription_freezes"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    resumed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_documents.id", ondelete="SET NULL"), nullable=True,
    )


class Refund(BranchScopedMixin, BaseModel):
    """Money paid back when a membership is cancelled (RF-0001 per gym). Bank account numbers are Fernet PII."""
    __tablename__ = "payment_refunds"
    __table_args__ = (UniqueConstraint("organization_id", "refund_no", name="uq_payment_refunds_org_no"),)

    refund_no: Mapped[str] = mapped_column(String(20), nullable=False)
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_subscriptions.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_payments.id", ondelete="SET NULL"), nullable=True,
    )
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)       # what the plan was paid
    deduction_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)            # paid back
    refund_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    refund_mode: Mapped[PaymentMode] = mapped_column(Enum(PaymentMode, name="payment_mode", create_type=False),
                                                     nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    account_holder: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_account_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(11), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    upi_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(80), nullable=True)            # UTR / transaction id


class MemberAssessment(BranchScopedMixin, BaseModel):
    """A fitness assessment on a date (taken again later to see progress). `movements` = {test code: rating}."""
    __tablename__ = "member_assessments"

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    assessed_on: Mapped[date] = mapped_column(Date, nullable=False)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    waist_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_heart_rate: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)       # bpm
    bp_systolic: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    bp_diastolic: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    lifestyle: Mapped[str | None] = mapped_column(String(20), nullable=True)                 # Lifestyle enum
    medical_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    past_injuries: Mapped[str | None] = mapped_column(Text, nullable=True)
    surgeries: Mapped[str | None] = mapped_column(Text, nullable=True)
    static_notes: Mapped[str | None] = mapped_column(Text, nullable=True)                    # posture
    movements: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    dynamic_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
