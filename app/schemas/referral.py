"""Pydantic v2 schemas — referral rewards and the referral tree."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema

from app.schemas.common import FormSchema


class TierIn(FormSchema):
    min_referrals: int = Field(ge=1, le=100)
    reward: str = Field(min_length=1, max_length=150)


class ProgramIn(FormSchema):
    """The reward for one month (this month or a coming one)."""
    month_key: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    title: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    tiers: list[TierIn] = Field(min_length=1, max_length=10)


class TierOut(TessBaseSchema):
    min_referrals: int
    reward: str


class ProgramOut(TessBaseSchema):
    month_key: str
    month_label: str                          # "November 2026"
    is_set: bool                              # False = no reward for this month (desk: contact admin)
    title: str | None = None
    notes: str | None = None
    tiers: list[TierOut] = []


class ReferralStatus(TessBaseSchema):
    current: ProgramOut
    next: ProgramOut
    days_left: int                            # in the current month


class PersonBrief(TessBaseSchema):
    member_id: UUID
    name: str
    registration_id: str
    phone: str
    plan_name: str | None = None              # latest membership
    plan_end: date | None = None
    joining_date: date


class EligibleRow(PersonBrief):
    referral_count: int                       # people they referred who joined (and paid) this month
    reward: str | None = None                 # reward reached (or given) this month
    eligible: bool
    given: bool
    next_reward: str | None = None
    needed_for_next: int | None = None
    referred: list[PersonBrief]


class EligibleList(TessBaseSchema):
    month_key: str
    month_label: str
    is_set: bool
    rows: list[EligibleRow]


class RewardRow(TessBaseSchema):
    id: UUID
    member_id: UUID
    name: str
    registration_id: str
    phone: str
    month_key: str
    month_label: str
    referral_count: int
    reward: str
    status: str                               # PENDING / GIVEN
    given_on: date | None = None
    note: str | None = None
    referred: list[PersonBrief]               # the referrals it was earned for


class ReferralCounts(TessBaseSchema):
    eligible: int                             # reached a reward this month, not given yet
    pending: int                              # earned in ended months, to hand over
    rewarded: int


class GiveIn(FormSchema):
    member_id: UUID
    month_key: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")   # None = this month
    note: str | None = Field(default=None, max_length=500)


class GiveOut(TessBaseSchema):
    member_id: UUID
    name: str
    reward: str
    month_label: str


class TreeNode(PersonBrief):
    referral_count: int                       # people they referred directly
    paid: bool = False                        # paid for a plan (only paid referrals count for rewards)
    rewarded: bool                            # got a referral reward
    reward_due: bool                          # has a reward waiting (pending / reached this month)
    counted: bool                             # their joining counted for their referrer's reward
    counted_status: str | None = None         # GIVEN / PENDING: the reward they were counted for
    children: list["TreeNode"] = []


class TreeReward(TessBaseSchema):
    id: UUID
    month_key: str
    month_label: str
    reward: str
    status: str
    given_on: date | None = None
    referral_count: int
    note: str | None = None
    referred: list[PersonBrief]


class ReferralTree(TessBaseSchema):
    root: TreeNode
    referred_by: PersonBrief | None = None
    total_referred: int                       # everyone in the returned levels (direct only by default)
    rewards: list[TreeReward]


TreeNode.model_rebuild()
