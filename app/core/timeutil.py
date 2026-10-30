"""Gym-local calendar helpers. Timestamps are stored UTC; business dates use APP_TIMEZONE."""
from __future__ import annotations

import calendar
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.config import settings


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.APP_TIMEZONE)


def today() -> date:
    return datetime.now(_tz()).date()


def now_time() -> time:
    return datetime.now(_tz()).time().replace(microsecond=0)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def month_key(year: int, month: int) -> str:
    """Salary month key — `MM-YYYY`, as in the original system."""
    return f"{month:02d}-{year}"
