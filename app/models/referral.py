"""Referral rewards — the gym's reward for each month (tiers by referral count) and the rewards earned / given."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, BranchScopedMixin


class ReferralProgram(BaseModel):
    """What referrers get for one calendar month (gym-wide). It works only in its own month: when the month ends
    the reward is over, until the admin sets the next month's."""
    __tablename__ = "referral_programs"
    __table_args__ = (UniqueConstraint("organization_id", "month_key", name="uq_referral_programs_org_month"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_organizations.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    month_key: Mapped[str] = mapped_column(String(7), nullable=False)          # "2026-11"
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)      # "November referral offer"
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # After the month ended, its earned rewards were written as PENDING (done once, on the first look after).
    settled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class ReferralTier(BaseModel):
    """Refer at least `min_referrals` people in the month → `reward` (the highest tier reached counts)."""
    __tablename__ = "referral_tiers"
    __table_args__ = (UniqueConstraint("program_id", "min_referrals", name="uq_referral_tiers_program_min"),)

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("referral_programs.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    min_referrals: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reward: Mapped[str] = mapped_column(String(150), nullable=False)          # "Protein shaker", "1 month free"


class ReferralReward(BranchScopedMixin, BaseModel):
    """A reward a member earned for one month's referrals: PENDING until the desk hands it over (GIVEN).
    The referred members it was earned for are in referral_reward_members."""
    __tablename__ = "referral_rewards"
    __table_args__ = (UniqueConstraint("member_id", "month_key", name="uq_referral_rewards_member_month"),)

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("referral_programs.id", ondelete="RESTRICT"), nullable=False,
    )
    month_key: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    referral_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reward: Mapped[str] = mapped_column(String(150), nullable=False)          # snapshot of the tier's reward
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING",
                                        server_default=text("'PENDING'"))   # PENDING / GIVEN
    given_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    given_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReferralRewardMember(BaseModel):
    """One referred member counted for a reward (the reward's history: 'because A, B and C joined')."""
    __tablename__ = "referral_reward_members"
    __table_args__ = (UniqueConstraint("reward_id", "referred_member_id", name="uq_referral_reward_members"),)

    reward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("referral_rewards.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    referred_member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
