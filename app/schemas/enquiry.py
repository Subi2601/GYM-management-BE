"""Pydantic v2 schemas — public enquiry form."""
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema

from app.core.enums import FitnessGoal
from app.schemas.common import FormSchema, Phone

PreferredTime = Literal["MORNING", "AFTERNOON", "EVENING"]
JoinWhen = Literal["THIS_WEEK", "THIS_MONTH", "LATER"]


class EnquiryFormInfo(TessBaseSchema):
    """GET /public/enquiry/{token} — what the form page shows (no login)."""
    organization_name: str
    branch_name: str
    branch_location: str | None = None
    contact_phone: str | None = None
    logo_url: str | None = None
    terms_url: str | None = None
    # Trial class offer (Gym settings); the form shows the option only when enabled.
    trial_enabled: bool = False
    trial_days: int = 0
    trial_fee: float = 0
    trial_book_ahead_days: int = 0            # latest start = today + this


class EnquirySubmit(FormSchema):
    name: str = Field(min_length=1, max_length=120)
    phone: Phone
    goal: FitnessGoal | None = None
    preferred_time: PreferredTime | None = None
    join_when: JoinWhen | None = None
    location: str | None = Field(default=None, max_length=150)      # area they live in
    message: str | None = Field(default=None, max_length=500)
    # Book the trial class starting on `trial_date` (today … today + trial_book_ahead_days).
    trial: bool = False
    trial_date: date | None = None
    # Honeypot: hidden on the page, so people leave it empty; bots that fill every field get dropped.
    website: str | None = Field(default=None, max_length=200)


class EnquiryResult(TessBaseSchema):
    name: str
    branch_name: str
    # Set when a trial was booked by this submit.
    trial_start: date | None = None
    trial_end: date | None = None
    trial_fee: float | None = None
    # Asked for a trial but this phone already had one: the gym will call instead.
    trial_used: bool = False


class EnquiryLink(TessBaseSchema):
    """GET /leads/enquiry-form — the branch's public form link token (staff side)."""
    branch_id: UUID
    branch_name: str
    token: str
