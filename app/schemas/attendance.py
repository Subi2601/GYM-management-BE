"""Pydantic v2 schemas — staff attendance."""
from __future__ import annotations

import datetime as dt
from typing import Literal
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import AttendancePersonType, AttendanceSource, AttendanceStatus, EmployeeRole
from app.schemas.common import FormSchema


class AttendanceMark(FormSchema):
    employee_id: UUID
    status: AttendanceStatus
    notes: str | None = Field(default=None, max_length=300)
    date: dt.date | None = None        # defaults to today


class AttendanceResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    employee_id: UUID
    employee_name: str
    employee_code: str
    employee_role: EmployeeRole
    attendance_date: dt.date
    check_in_time: dt.time | None = None
    check_out_time: dt.time | None = None
    status: AttendanceStatus
    notes: str | None = None
    # From the day's sessions (daily view only): still inside, number of visits, closed-visit minutes,
    # and how the first check-in was recorded.
    inside: bool = False
    visits: int = 0
    worked_minutes: int = 0
    source: AttendanceSource | None = None


class UnmarkedEmployee(UUIDSchema):
    employee_code: str
    name: str
    role: EmployeeRole


class DailyAttendanceResponse(TessBaseSchema):
    date: dt.date
    records: list[AttendanceResponse]
    not_marked: list[UnmarkedEmployee]


class AttendanceSummary(TessBaseSchema):
    present: int
    absent: int
    late: int
    half_day: int
    on_leave: int
    total_days_in_month: int


class MonthlyAttendanceResponse(TessBaseSchema):
    employee_id: UUID | None = None
    month_year: str
    records: list[AttendanceResponse]
    summary: AttendanceSummary


# ── members ──────────────────────────────────────────────────────────────

class MemberCheckIn(FormSchema):
    member_id: UUID


class SessionCheckout(FormSchema):
    """Front desk closes a visit. Omit the time for now (today only); a past day needs it."""
    check_out_time: dt.time | None = None


class MemberSessionResponse(UUIDSchema):
    member_id: UUID
    member_name: str
    registration_id: str
    phone: str
    session_date: dt.date
    check_in_time: dt.time
    check_out_time: dt.time | None = None
    in_source: AttendanceSource
    out_source: AttendanceSource | None = None
    denied_reason: str | None = None          # refused QR check-in (e.g. membership expired)
    duration_minutes: int | None = None


class MemberDaySummary(TessBaseSchema):
    inside: int
    checked_in: int       # distinct members with an accepted check-in
    visits: int
    denied: int


class MemberDailyResponse(TessBaseSchema):
    date: dt.date
    records: list[MemberSessionResponse]
    summary: MemberDaySummary


class CheckResult(TessBaseSchema):
    """Outcome of a check-in / check-out (front desk or QR)."""
    direction: Literal["IN", "OUT"]
    person_type: AttendancePersonType
    name: str
    time: dt.time
    late: bool = False
    duration_minutes: int | None = None


# ── QR posters + linked phones (admin) ───────────────────────────────────

class AttendanceQrResponse(TessBaseSchema):
    branch_id: UUID
    branch_name: str
    checkin_token: str
    latitude: float | None = None
    longitude: float | None = None
    geofence_m: int


class AttendanceLocationUpdate(FormSchema):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    geofence_m: int = Field(default=150, ge=50, le=1000)


class LinkedDeviceResponse(UUIDSchema):
    person_type: AttendancePersonType
    person_name: str
    person_code: str
    user_agent: str | None = None
    last_used_at: dt.datetime | None = None
    created_at: dt.datetime


# ── public scan page ─────────────────────────────────────────────────────

class CheckinPerson(TessBaseSchema):
    name: str
    person_type: AttendancePersonType


class CheckinInfoResponse(TessBaseSchema):
    branch_name: str
    organization_name: str
    location_required: bool
    person: CheckinPerson | None = None      # who this phone is linked to (None = verify first)


class CheckinVerify(FormSchema):
    phone: str = Field(min_length=10, max_length=15, pattern=r"^[0-9+\s-]+$")
    id_number: str = Field(min_length=1, max_length=20)


class CheckinScan(FormSchema):
    direction: Literal["in", "out"]
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
