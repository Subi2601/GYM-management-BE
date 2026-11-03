"""Pydantic v2 schemas — employees, client feedback, trainer PT clients."""
from __future__ import annotations

from datetime import date, time
from typing import Annotated, Any
from uuid import UUID

from pydantic import BeforeValidator, EmailStr, Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import AttendanceStatus, EmployeeRole, EmployeeStatus, FitnessGoal, PTStatus, SalaryStatus
from app.schemas.common import FormSchema, Phone


def _upper_compact(value: Any) -> Any:
    """PAN / IFSC are typed in any case and sometimes with spaces — normalise before the pattern check."""
    return value.replace(" ", "").upper() if isinstance(value, str) else value


def _digits_only(value: Any) -> Any:
    """Aadhaar is often written `1234 5678 9012` — keep the digits only."""
    return value.replace(" ", "").replace("-", "") if isinstance(value, str) else value


Pan = Annotated[str, BeforeValidator(_upper_compact),
                Field(pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$", description="PAN, e.g. ABCDE1234F")]
Aadhaar = Annotated[str, BeforeValidator(_digits_only),
                    Field(pattern=r"^\d{12}$", description="12-digit Aadhaar number")]
Ifsc = Annotated[str, BeforeValidator(_upper_compact),
                 Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$", description="IFSC, e.g. SBIN0001234")]
BankAccount = Annotated[str, BeforeValidator(_digits_only),
                        Field(pattern=r"^[0-9A-Za-z]{6,20}$", description="Bank account number")]


def _lower_strip(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


# UPI virtual payment address: handle@bank, e.g. ravi.kumar@okaxis / 9876543210@ybl
UpiId = Annotated[str, BeforeValidator(_lower_strip),
                  Field(max_length=100, pattern=r"^[a-z0-9._-]{2,64}@[a-z][a-z0-9]{1,31}$",
                        description="UPI ID, e.g. name@okaxis")]


class EmployeeCreate(FormSchema):
    """Profile only — payroll and bank details are set separately (PUT /employees/{id}/payroll)."""
    name: str = Field(min_length=1, max_length=120)
    phone: Phone
    email: EmailStr = Field(max_length=150)     # column is VARCHAR(150)
    address: str = Field(min_length=1, max_length=300)
    role: EmployeeRole
    education: str | None = Field(default=None, max_length=150)
    experience: str | None = Field(default=None, max_length=150)
    # Identity and emergency contact are optional.
    aadhar_number: Aadhaar | None = None
    pan_number: Pan | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: Phone | None = None
    emergency_contact_relation: str | None = Field(default=None, max_length=60)
    date_of_joining: date
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    # Shift timings — both the morning and the evening shift (order rules in EmployeeService).
    morning_start: time
    morning_end: time
    evening_start: time
    evening_end: time


class EmployeeUpdate(FormSchema):
    """Partial update — only fields present in the body are applied."""
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: Phone | None = None
    email: EmailStr | None = Field(default=None, max_length=150)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    role: EmployeeRole | None = None
    education: str | None = Field(default=None, max_length=150)
    experience: str | None = Field(default=None, max_length=150)
    aadhar_number: Aadhaar | None = None
    pan_number: Pan | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=120)
    emergency_contact_phone: Phone | None = None
    emergency_contact_relation: str | None = Field(default=None, max_length=60)
    date_of_joining: date | None = None
    status: EmployeeStatus | None = None
    morning_start: time | None = None
    morning_end: time | None = None
    evening_start: time | None = None
    evening_end: time | None = None


class EmployeePayrollUpdate(FormSchema):
    """Payroll and bank details. Bank name, account and IFSC go together (or are all empty, e.g. paid in cash);
    the UPI ID is optional on its own. `bank_account_number` left out of the body keeps the stored one
    (clients without pii:view only see it masked)."""
    base_salary: float = Field(ge=0, le=10_000_000)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_number: BankAccount | None = None
    ifsc_code: Ifsc | None = None
    upi_id: UpiId | None = None


class EmployeeResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    employee_code: str
    name: str
    phone: str
    email: str | None = None
    address: str | None = None
    role: EmployeeRole
    education: str | None = None
    experience: str | None = None
    # PII — decrypted for pii:view, masked (XXXX-XXXX-1234) otherwise
    aadhar_number: str | None = None
    pan_number: str | None = None
    bank_account_number: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relation: str | None = None
    base_salary: float
    bank_name: str | None = None
    ifsc_code: str | None = None
    upi_id: str | None = None
    status: EmployeeStatus
    average_rating: float | None = None
    date_of_joining: date
    date_of_termination: date | None = None
    morning_start: time | None = None
    morning_end: time | None = None
    evening_start: time | None = None
    evening_end: time | None = None


class TrainerOption(UUIDSchema):
    employee_code: str
    name: str
    phone: str


class FeedbackCreate(FormSchema):
    client_name: str = Field(min_length=1, max_length=120)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    feedback_date: date | None = None       # defaults to today


class FeedbackResponse(UUIDSchema, TimestampMixin):
    employee_id: UUID
    client_name: str
    rating: int
    comment: str | None = None
    feedback_date: date


class FeedbackCreated(TessBaseSchema):
    feedback: FeedbackResponse
    average_rating: float | None = None


class PTClientResponse(UUIDSchema):
    member_id: UUID
    member_name: str
    plan_id: UUID | None = None
    plan_name: str | None = None
    goal: FitnessGoal | None = None
    total_sessions: int
    sessions_remaining: int
    start_date: date
    expiry_date: date
    status: PTStatus
    is_paid: bool


class AttendanceDay(TessBaseSchema):
    date: date
    status: AttendanceStatus
    check_in: time | None = None
    check_out: time | None = None


class AttendanceMonth(TessBaseSchema):
    """One month of attendance for the profile. `days_elapsed` = days of the month up to today (all for past months)."""
    month_year: str                         # MM-YYYY
    days_in_month: int
    days_elapsed: int
    present: int
    late: int
    absent: int
    half_day: int
    on_leave: int
    days: list[AttendanceDay]


class LastPayout(TessBaseSchema):
    month_year: str
    net_salary: float
    status: SalaryStatus
    paid_date: date | None = None


class PayrollSummary(TessBaseSchema):
    base_salary: float
    last_payout: LastPayout | None = None


class TrainingSummary(TessBaseSchema):
    """Trainers only: personal-training clients and client feedback."""
    active_clients: int
    pt_clients: list[PTClientResponse]
    feedbacks: list[FeedbackResponse]
    average_rating: float | None = None


class EmployeeProfileResponse(TessBaseSchema):
    """Staff details page. Sections depend on the employee and the caller:
    `payroll` needs salary:list (else null); `training` is only filled for TRAINER employees."""
    employee: EmployeeResponse
    attendance: AttendanceMonth
    payroll: PayrollSummary | None = None
    training: TrainingSummary | None = None


class EmployeeCounts(TessBaseSchema):
    """Row count per list tab (GET /employees/counts) — same rules as `status`."""
    active: int
    archive: int
    all: int
