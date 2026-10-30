"""Pydantic v2 schemas — staff attendance."""
from __future__ import annotations

import datetime as dt
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import AttendanceStatus, EmployeeRole
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
