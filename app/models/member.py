"""Gym members (clients) and sales leads."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Enum, Float, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import Gender, LeadStatus, MemberStatus
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
    fitness_goal: Mapped[str | None] = mapped_column(String(200), nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    joining_date: Mapped[date] = mapped_column(Date, nullable=False)
    id_proof_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    id_proof_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet PII
    status: Mapped[MemberStatus] = mapped_column(
        Enum(MemberStatus, name="member_status"), nullable=False,
        default=MemberStatus.ACTIVE, server_default=text("'ACTIVE'"),
    )


class Lead(BranchScopedMixin, BaseModel):
    __tablename__ = "lead_leads"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    location: Mapped[str | None] = mapped_column(String(150), nullable=True)
    goal: Mapped[str | None] = mapped_column(String(150), nullable=True)
    plan_to_join_date: Mapped[date | None] = mapped_column(Date, nullable=True)
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
