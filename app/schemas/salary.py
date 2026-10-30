"""Pydantic v2 schemas — monthly salary / payroll."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import EmployeeRole, PaymentMode, SalaryStatus
from app.schemas.common import FormSchema


class SalaryCalculate(FormSchema):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    employee_id: UUID | None = None     # omitted → every ACTIVE employee of the branch


class SalaryPay(FormSchema):
    payment_method: PaymentMode
    paid_date: date | None = None       # defaults to today


class SalaryResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    employee_id: UUID
    employee_name: str
    employee_code: str
    employee_role: EmployeeRole
    month_year: str
    base_salary: float
    days_present: int
    days_absent: int
    days_late: int
    deductions: float
    bonus: float
    till_now_salary: float
    net_salary: float
    status: SalaryStatus
    paid_date: date | None = None
    payment_method: str | None = None
    absent_dates: list[date] = []


class SalaryMonthResponse(TessBaseSchema):
    month_year: str
    items: list[SalaryResponse]
    total_payout: float


class SalaryCalcResult(TessBaseSchema):
    employee_id: UUID
    employee_name: str
    employee_code: str
    outcome: str                        # "CALCULATED" | "SKIPPED_PAID"
    salary: SalaryResponse


class SalaryCalculateResponse(TessBaseSchema):
    month_year: str
    calculated: int
    skipped_paid: int
    results: list[SalaryCalcResult]
