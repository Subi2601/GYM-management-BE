"""Staff: employees, client feedback, daily attendance and monthly salary."""
from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import (Date, Enum, Float, ForeignKey, Integer, Numeric, SmallInteger, String, Text, Time,
                        UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AttendanceStatus, EmployeeRole, EmployeeStatus, SalaryStatus
from app.models.base import BaseModel, BranchScopedMixin


class Employee(BranchScopedMixin, BaseModel):
    __tablename__ = "staff_employees"
    __table_args__ = (
        UniqueConstraint("branch_id", "employee_code", name="uq_staff_employees_branch_code"),
        UniqueConstraint("branch_id", "phone", name="uq_staff_employees_branch_phone"),
    )

    employee_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # SG-EMP-001
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(15), nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    role: Mapped[EmployeeRole] = mapped_column(Enum(EmployeeRole, name="employee_role"), nullable=False)
    education: Mapped[str | None] = mapped_column(String(150), nullable=True)
    experience: Mapped[str | None] = mapped_column(String(150), nullable=True)
    # PII — Fernet-encrypted, masked for callers without pii:view
    aadhar_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    pan_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    id_proof_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    id_proof_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(15), nullable=True)
    emergency_contact_relation: Mapped[str | None] = mapped_column(String(60), nullable=True)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0,
                                                 server_default=text("0"))
    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bank_account_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[EmployeeStatus] = mapped_column(
        Enum(EmployeeStatus, name="employee_status"), nullable=False,
        default=EmployeeStatus.ACTIVE, server_default=text("'ACTIVE'"),
    )
    average_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    date_of_joining: Mapped[date] = mapped_column(Date, nullable=False)
    date_of_termination: Mapped[date | None] = mapped_column(Date, nullable=True)


class EmployeeFeedback(BranchScopedMixin, BaseModel):
    __tablename__ = "staff_feedbacks"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_employees.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    client_name: Mapped[str] = mapped_column(String(120), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1–5
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_date: Mapped[date] = mapped_column(Date, nullable=False)


class Attendance(BranchScopedMixin, BaseModel):
    __tablename__ = "staff_attendance"
    __table_args__ = (
        UniqueConstraint("employee_id", "attendance_date", name="uq_staff_attendance_employee_date"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_employees.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    check_in_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    check_out_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, name="attendance_status"), nullable=False,
        default=AttendanceStatus.PRESENT, server_default=text("'PRESENT'"),
    )
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Salary(BranchScopedMixin, BaseModel):
    __tablename__ = "staff_salaries"
    __table_args__ = (
        UniqueConstraint("employee_id", "month_year", name="uq_staff_salaries_employee_month"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff_employees.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    month_year: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # MM-YYYY
    base_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    days_present: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days_absent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    days_late: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deductions: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    bonus: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    till_now_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    net_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    status: Mapped[SalaryStatus] = mapped_column(
        Enum(SalaryStatus, name="salary_status"), nullable=False,
        default=SalaryStatus.PENDING, server_default=text("'PENDING'"),
    )
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(30), nullable=True)
