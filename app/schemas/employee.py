"""Pydantic v2 schemas — employees, client feedback, trainer PT clients."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from pydantic import BeforeValidator, EmailStr, Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import EmployeeRole, EmployeeStatus, PTStatus
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


class EmployeeCreate(FormSchema):
    name: str = Field(min_length=1, max_length=120)
    phone: Phone
    email: EmailStr
    address: str = Field(min_length=1, max_length=300)
    role: EmployeeRole
    education: str | None = Field(default=None, max_length=150)
    experience: str | None = Field(default=None, max_length=150)
    aadhar_number: Aadhaar
    pan_number: Pan
    id_proof_type: str = Field(min_length=1, max_length=40)
    id_proof_number: str = Field(min_length=1, max_length=40)
    emergency_contact_name: str = Field(min_length=1, max_length=120)
    emergency_contact_phone: Phone
    emergency_contact_relation: str = Field(min_length=1, max_length=60)
    base_salary: float = Field(ge=0, le=10_000_000)
    bank_name: str = Field(min_length=1, max_length=120)
    bank_account_number: BankAccount
    ifsc_code: Ifsc
    date_of_joining: date
    status: EmployeeStatus = EmployeeStatus.ACTIVE


class EmployeeUpdate(FormSchema):
    """Partial update — only fields present in the body are applied."""
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: Phone | None = None
    email: EmailStr | None = None
    address: str | None = Field(default=None, min_length=1, max_length=300)
    role: EmployeeRole | None = None
    education: str | None = Field(default=None, max_length=150)
    experience: str | None = Field(default=None, max_length=150)
    aadhar_number: Aadhaar | None = None
    pan_number: Pan | None = None
    id_proof_type: str | None = Field(default=None, min_length=1, max_length=40)
    id_proof_number: str | None = Field(default=None, min_length=1, max_length=40)
    emergency_contact_name: str | None = Field(default=None, min_length=1, max_length=120)
    emergency_contact_phone: Phone | None = None
    emergency_contact_relation: str | None = Field(default=None, min_length=1, max_length=60)
    base_salary: float | None = Field(default=None, ge=0, le=10_000_000)
    bank_name: str | None = Field(default=None, min_length=1, max_length=120)
    bank_account_number: BankAccount | None = None
    ifsc_code: Ifsc | None = None
    date_of_joining: date | None = None
    status: EmployeeStatus | None = None


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
    id_proof_type: str | None = None
    id_proof_number: str | None = None
    bank_account_number: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relation: str | None = None
    base_salary: float
    bank_name: str | None = None
    ifsc_code: str | None = None
    status: EmployeeStatus
    average_rating: float | None = None
    date_of_joining: date
    date_of_termination: date | None = None


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
    goal: str | None = None
    total_sessions: int
    sessions_remaining: int
    start_date: date
    expiry_date: date
    status: PTStatus
    is_paid: bool


class EmployeeProfileResponse(TessBaseSchema):
    employee: EmployeeResponse
    feedbacks: list[FeedbackResponse]
    pt_clients: list[PTClientResponse]
    average_rating: float | None = None
