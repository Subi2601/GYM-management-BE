"""Pydantic v2 schemas — renewals (memberships ending soon / lapsed) and reminders."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from shared.schemas.base_schema import TessBaseSchema


class RenewalRow(TessBaseSchema):
    subscription_id: UUID
    member_id: UUID
    member_name: str
    registration_id: str
    phone: str
    plan_name: str
    end_date: date
    days_left: int                     # negative = days since it lapsed
    reminded_at: datetime | None = None
    reminder_count: int


class RenewalCounts(TessBaseSchema):
    due: int
    overdue: int
    reminded: int
    all: int
