"""Gym members (clients) and sales leads."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, Float, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import FitnessGoal, Gender, LeadSource, LeadStatus, MemberStatus, PaymentMode
from app.models.base import BaseModel, BranchScopedMixin


class Member(BranchScopedMixin, BaseModel):
    __tablename__ = "member_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "registration_id", name="uq_member_members_org_reg"),
        UniqueConstraint("branch_id", "phone", name="uq_member_members_branch_phone"),
    )

    registration_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # SG-001
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    gender: Mapped[Gender] = mapped_column(
        Enum(Gender, name="gender"), nullable=False, default=Gender.MALE, server_default=text("'MALE'"),
    )
    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(5), nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)      # kg
    height: Mapped[float | None] = mapped_column(Float, nullable=True)      # cm
    fitness_goal: Mapped[FitnessGoal | None] = mapped_column(
        Enum(FitnessGoal, native_enum=False, create_constraint=False, length=200), nullable=True,
    )
    emergency_contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    id_proof_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    id_proof_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet PII
    status: Mapped[MemberStatus] = mapped_column(
        Enum(MemberStatus, name="member_status"), nullable=False,
        default=MemberStatus.ACTIVE, server_default=text("'ACTIVE'"),
    )
    # The member who referred this one (referral tree / monthly referral rewards).
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="SET NULL"), nullable=True, index=True,
    )


class Lead(BranchScopedMixin, BaseModel):
    __tablename__ = "lead_leads"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(150), nullable=True)
    goal: Mapped[FitnessGoal | None] = mapped_column(
        Enum(FitnessGoal, native_enum=False, create_constraint=False, length=150), nullable=True,
    )
    plan_to_join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # NULL only on leads created before the source was captured.
    source: Mapped[LeadSource | None] = mapped_column(
        Enum(LeadSource, native_enum=False, create_constraint=False, length=20), nullable=True, index=True,
    )
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status"), nullable=False,
        default=LeadStatus.NEW, server_default=text("'NEW'"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # follow-up history, newest last
    next_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    converted_member_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="SET NULL"), nullable=True,
    )
    # Source REFERRAL: the member who sent them (copied to the member on conversion).
    referred_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="SET NULL"), nullable=True,
    )
    # Trial class (one per lead): dates from the gym's trial days, the fee at booking (0 = free),
    # when / how it was paid, and the visits the desk marked.
    trial_start: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    trial_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    trial_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    trial_paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    trial_payment_mode: Mapped[PaymentMode | None] = mapped_column(
        Enum(PaymentMode, name="payment_mode", create_type=False), nullable=True,
    )
    trial_visits: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default=text("0"))
    trial_last_visit: Mapped[date | None] = mapped_column(Date, nullable=True)
