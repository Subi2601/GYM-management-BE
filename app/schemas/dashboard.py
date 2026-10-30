"""Pydantic v2 schemas — dashboard summary."""
from __future__ import annotations

from shared.schemas.base_schema import TessBaseSchema


class GrowthPoint(TessBaseSchema):
    month: str                # "Oct 2026"
    new_members: int
    revenue: float


class DashboardSummary(TessBaseSchema):
    total_members: int
    active_members: int       # latest MEMBERSHIP subscription not yet ended
    total_revenue: float
    today_revenue: float
    expiring_this_week: int   # latest MEMBERSHIP ends within the next 7 days
    open_leads: int           # NEW + FOLLOW_UP
    growth: list[GrowthPoint] # last 6 months, oldest first
