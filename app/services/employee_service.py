"""Employees business logic — codes, uniqueness, PII, termination, feedback rating, profile."""
from __future__ import annotations

from datetime import time
from decimal import Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.encryption import decrypt_pii, encrypt_pii, mask_pii
from app.core.enums import AttendanceStatus, EmployeeRole, EmployeeStatus, PTStatus
from app.core.scope import BranchScope
from app.models.staff import Employee, EmployeeFeedback
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.salary_repository import SalaryRepository
from app.services.staff_login_service import StaffLoginService

_SHIFT_FIELDS = ("morning_start", "morning_end", "evening_start", "evening_end")
# Profile fields set by create / update. Payroll and bank details have their own command (update_payroll).
_PLAIN_FIELDS = ("name", "phone", "email", "address", "role", "education", "experience",
                 "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
                 "date_of_joining", "status", *_SHIFT_FIELDS)
# request field → encrypted column (profile PII; the bank account is written by update_payroll)
_PII_FIELDS = {"aadhar_number": "aadhar_number_enc", "pan_number": "pan_number_enc"}
# Returned (decrypted or masked) on every employee.
_PII_OUT = {**_PII_FIELDS, "bank_account_number": "bank_account_number_enc"}
# Fields the UI requires — a partial update may change them but never clear them.
# (Identity numbers and the emergency contact are optional and may be cleared; clearing a shift time is
# rejected by _check_shifts with a clear message instead of being silently ignored.)
_NOT_CLEARABLE = {"name", "phone", "email", "address", "role", "date_of_joining", "status"}


def _check_shifts(morning_start: time | None, morning_end: time | None,
                  evening_start: time | None, evening_end: time | None) -> None:
    """Gyms run a morning and an evening session and staff work both: every time is required,
    each shift ends after it starts, and the morning shift ends before the evening shift starts."""
    shifts = {"Morning": (morning_start, morning_end), "Evening": (evening_start, evening_end)}
    for label, (start, end) in shifts.items():
        if start is None or end is None:
            raise ValidationError(f"Enter the {label.lower()} shift from and to times")
        if start >= end:
            raise ValidationError(f"{label} shift must end after it starts")
    if morning_end > evening_start:  # both set — checked above
        raise ValidationError("The morning shift must end before the evening shift starts")

STATUS_FILTERS: dict[str, tuple[EmployeeStatus, ...] | None] = {
    "active": (EmployeeStatus.ACTIVE,),
    "archive": (EmployeeStatus.TERMINATED,),
    "all": None,
}


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _rating(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


class EmployeeService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = EmployeeRepository(db)
        self._attendance = AttendanceRepository(db)
        self._salaries = SalaryRepository(db)

    # ── output builders ──────────────────────────────────────────────────
    @staticmethod
    def employee_out(e: Employee, *, show_pii: bool) -> dict:
        def pii(column: str) -> str | None:
            plain = decrypt_pii(getattr(e, column))
            return plain if show_pii else mask_pii(plain)

        return {
            "id": e.id, "branch_id": e.branch_id, "employee_code": e.employee_code,
            "name": e.name, "phone": e.phone, "email": e.email, "address": e.address, "role": e.role,
            "education": e.education, "experience": e.experience,
            **{field: pii(column) for field, column in _PII_OUT.items()},
            "emergency_contact_name": e.emergency_contact_name,
            "emergency_contact_phone": e.emergency_contact_phone,
            "emergency_contact_relation": e.emergency_contact_relation,
            "base_salary": float(e.base_salary or 0), "bank_name": e.bank_name, "ifsc_code": e.ifsc_code,
            "upi_id": e.upi_id,
            "status": e.status, "average_rating": _rating(e.average_rating),
            "date_of_joining": e.date_of_joining, "date_of_termination": e.date_of_termination,
            **{f: getattr(e, f) for f in _SHIFT_FIELDS},
            "created_at": e.created_at, "updated_at": e.updated_at,
        }

    @staticmethod
    def feedback_out(f: EmployeeFeedback) -> dict:
        return {"id": f.id, "employee_id": f.employee_id, "client_name": f.client_name, "rating": f.rating,
                "comment": f.comment, "feedback_date": f.feedback_date,
                "created_at": f.created_at, "updated_at": f.updated_at}

    @staticmethod
    def pt_client_out(pt, member_name: str, plan_name: str | None) -> dict:
        return {"id": pt.id, "member_id": pt.member_id, "member_name": member_name, "plan_id": pt.plan_id,
                "plan_name": plan_name, "goal": pt.goal, "total_sessions": pt.total_sessions,
                "sessions_remaining": pt.sessions_remaining, "start_date": pt.start_date,
                "expiry_date": pt.expiry_date, "status": pt.status, "is_paid": pt.is_paid}

    async def _require(self, employee_id: UUID, scope: BranchScope) -> Employee:
        employee = await self._repo.get_employee(employee_id, scope)
        if employee is None:
            raise NotFoundError("Employee")
        return employee

    # ── queries ──────────────────────────────────────────────────────────
    async def list_employees(self, scope: BranchScope, *, offset: int, limit: int, status_filter: str,
                             role: EmployeeRole | None, search: str | None, sort_by: str | None,
                             sort_dir: str, show_pii: bool) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_employees(scope, offset=offset, limit=limit,
                                                      statuses=STATUS_FILTERS.get(status_filter),
                                                      role=role, search=search, sort_by=sort_by, sort_dir=sort_dir)
        return [self.employee_out(e, show_pii=show_pii) for e in rows], total

    async def status_counts(self, scope: BranchScope) -> dict:
        return await self._repo.status_counts(scope, STATUS_FILTERS)

    async def get_employee(self, employee_id: UUID, scope: BranchScope, show_pii: bool) -> dict:
        return self.employee_out(await self._require(employee_id, scope), show_pii=show_pii)

    async def get_profile(self, employee_id: UUID, scope: BranchScope, *, show_pii: bool, show_payroll: bool,
                          month: int | None = None, year: int | None = None) -> dict:
        """Staff details page: profile + one month of attendance for everyone, payroll for salary:list callers,
        and personal-training clients / client feedback only for trainers."""
        employee = await self._require(employee_id, scope)
        return {
            "employee": self.employee_out(employee, show_pii=show_pii),
            "attendance": await self._attendance_month(employee, scope, month, year),
            "payroll": await self._payroll_summary(employee, scope) if show_payroll else None,
            "training": await self._training_summary(employee, scope)
            if employee.role == EmployeeRole.TRAINER else None,
        }

    async def _attendance_month(self, employee: Employee, scope: BranchScope,
                                month: int | None, year: int | None) -> dict:
        today = timeutil.today()
        month, year = month or today.month, year or today.year
        start, end = timeutil.month_bounds(year, month)
        rows = await self._attendance.list_for_range(scope, start, end, employee.id)
        counts = {s: 0 for s in AttendanceStatus}
        for row in rows:
            counts[row[0].status] += 1
        elapsed = 0 if start > today else end.day if end < today else today.day
        return {
            "month_year": timeutil.month_key(year, month), "days_in_month": end.day, "days_elapsed": elapsed,
            "present": counts[AttendanceStatus.PRESENT], "late": counts[AttendanceStatus.LATE],
            "absent": counts[AttendanceStatus.ABSENT], "half_day": counts[AttendanceStatus.HALF_DAY],
            "on_leave": counts[AttendanceStatus.ON_LEAVE],
            "days": [{"date": a.attendance_date, "status": a.status, "check_in": a.check_in_time,
                      "check_out": a.check_out_time} for a, *_ in rows],
        }

    async def _payroll_summary(self, employee: Employee, scope: BranchScope) -> dict:
        salaries = await self._salaries.list_for_employee(scope, employee.id)  # newest month first
        last = salaries[0][0] if salaries else None
        return {
            "base_salary": float(employee.base_salary or 0),
            "last_payout": {"month_year": last.month_year, "net_salary": float(last.net_salary),
                            "status": last.status, "paid_date": last.paid_date} if last else None,
        }

    async def _training_summary(self, employee: Employee, scope: BranchScope) -> dict:
        clients = await self._repo.list_pt_clients(employee.id, scope)
        feedbacks = await self._repo.list_feedbacks(employee.id, scope)
        pt_clients = [self.pt_client_out(*row) for row in clients]
        return {
            "active_clients": sum(1 for c in pt_clients if c["status"] == PTStatus.ACTIVE),
            "pt_clients": pt_clients,
            "feedbacks": [self.feedback_out(f) for f in feedbacks],
            "average_rating": _rating(employee.average_rating),
        }

    async def list_trainers(self, scope: BranchScope) -> list[dict]:
        rows = await self._repo.list_by_status(scope, EmployeeStatus.ACTIVE, role=EmployeeRole.TRAINER)
        return [{"id": e.id, "employee_code": e.employee_code, "name": e.name, "phone": e.phone} for e in rows]

    async def next_employee_code(self, branch_id: UUID) -> str:
        return f"SG-EMP-{await self._repo.last_code_number(branch_id) + 1:03d}"

    # ── commands ─────────────────────────────────────────────────────────
    async def create_employee(self, data, scope: BranchScope, actor: RequestContext, show_pii: bool) -> dict:
        branch_id = scope.require_branch()
        if data.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("A new employee cannot be created as TERMINATED")
        _check_shifts(*(getattr(data, f) for f in _SHIFT_FIELDS))
        if await self._repo.get_by_phone(branch_id, data.phone):
            raise ConflictError("An employee with this phone number already exists")
        employee = Employee(
            organization_id=scope.organization_id, branch_id=branch_id,
            employee_code=await self.next_employee_code(branch_id),
            **{f: getattr(data, f) for f in _PLAIN_FIELDS},
            base_salary=Decimal("0.00"),   # set later through update_payroll
            **{column: encrypt_pii(getattr(data, field)) for field, column in _PII_FIELDS.items()},
            created_by=actor.user_id,
        )
        await self._repo.add(employee)
        await self._repo.commit()
        return await self.get_employee(employee.id, scope, show_pii)

    async def update_employee(self, employee_id: UUID, data, scope: BranchScope, actor: RequestContext,
                              show_pii: bool) -> dict:
        employee = await self._require(employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("A terminated employee cannot be updated")
        sent = {f for f in data.model_fields_set
                if not (getattr(data, f) is None and f in _NOT_CLEARABLE)}
        if "status" in sent and data.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("Use the terminate action to terminate an employee")
        if "phone" in sent and data.phone != employee.phone:
            existing = await self._repo.get_by_phone(employee.branch_id, data.phone)
            if existing and existing.id != employee.id:
                raise ConflictError("An employee with this phone number already exists")
        # Shift rules apply to the timings as they will be after this update.
        if sent & set(_SHIFT_FIELDS):
            _check_shifts(*(getattr(data, f) if f in sent else getattr(employee, f) for f in _SHIFT_FIELDS))
        for field in _PLAIN_FIELDS:
            if field in sent:
                setattr(employee, field, getattr(data, field))
        for field, column in _PII_FIELDS.items():
            if field in sent:
                setattr(employee, column, encrypt_pii(getattr(data, field)))
        employee.updated_by = actor.user_id
        if sent & {"email", "name", "role"}:
            await StaffLoginService(self._db).sync_from_employee(employee, actor.user_id)
        await self._repo.commit()
        return await self.get_employee(employee.id, scope, show_pii)

    async def update_payroll(self, employee_id: UUID, data, scope: BranchScope, actor: RequestContext,
                             show_pii: bool) -> dict:
        scope.require_branch()
        employee = await self._require(employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("A terminated employee cannot be updated")
        employee.base_salary = _money(data.base_salary)
        employee.bank_name = data.bank_name
        employee.ifsc_code = data.ifsc_code
        employee.upi_id = data.upi_id
        if "bank_account_number" in data.model_fields_set:
            employee.bank_account_number_enc = encrypt_pii(data.bank_account_number)
        bank = (employee.bank_name, employee.bank_account_number_enc, employee.ifsc_code)
        if any(bank) and not all(bank):
            raise ValidationError("Enter bank name, account number and IFSC code together")
        employee.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_employee(employee.id, scope, show_pii)

    async def terminate_employee(self, employee_id: UUID, scope: BranchScope, actor: RequestContext,
                                 show_pii: bool) -> dict:
        scope.require_branch()
        employee = await self._require(employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("Employee is already terminated")
        employee.status = EmployeeStatus.TERMINATED
        employee.date_of_termination = timeutil.today()
        employee.updated_by = actor.user_id
        await StaffLoginService(self._db).disable_for_employee(employee.id, actor.user_id)
        await self._repo.commit()
        return await self.get_employee(employee.id, scope, show_pii)

    async def add_feedback(self, employee_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        employee = await self._require(employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("Feedback cannot be added for a terminated employee")
        feedback = EmployeeFeedback(
            organization_id=employee.organization_id, branch_id=employee.branch_id, employee_id=employee.id,
            client_name=data.client_name, rating=data.rating, comment=data.comment,
            feedback_date=data.feedback_date or timeutil.today(), created_by=actor.user_id,
        )
        await self._repo.add(feedback)
        employee.average_rating = _rating(await self._repo.average_rating(employee.id, scope))
        employee.updated_by = actor.user_id
        await self._repo.commit()
        return {"feedback": self.feedback_out(feedback), "average_rating": employee.average_rating}
