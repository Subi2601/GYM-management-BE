"""Attendance business logic — one record per employee per day, check-in/out, daily + monthly views."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import AttendanceStatus, EmployeeStatus
from app.core.scope import BranchScope
from app.models.staff import Attendance, Employee
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository

_CHECK_IN_STATUSES = (AttendanceStatus.PRESENT, AttendanceStatus.LATE)


class AttendanceService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = AttendanceRepository(db)
        self._employees = EmployeeRepository(db)

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def attendance_out(a: Attendance, name: str, code: str, role) -> dict:
        return {"id": a.id, "branch_id": a.branch_id, "employee_id": a.employee_id, "employee_name": name,
                "employee_code": code, "employee_role": role, "attendance_date": a.attendance_date,
                "check_in_time": a.check_in_time, "check_out_time": a.check_out_time, "status": a.status,
                "notes": a.notes, "created_at": a.created_at, "updated_at": a.updated_at}

    async def _require_employee(self, employee_id: UUID, scope: BranchScope) -> Employee:
        employee = await self._employees.get_employee(employee_id, scope)
        if employee is None:
            raise NotFoundError("Employee")
        return employee

    async def _row_out(self, attendance_id: UUID, scope: BranchScope) -> dict:
        return self.attendance_out(*await self._repo.get_row(attendance_id, scope))

    # ── queries ──────────────────────────────────────────────────────────
    async def daily(self, scope: BranchScope, day: date | None) -> dict:
        day = day or timeutil.today()
        records = await self._repo.list_for_date(scope, day)
        unmarked = await self._repo.unmarked_active_employees(scope, day)
        return {
            "date": day,
            "records": [self.attendance_out(*r) for r in records],
            "not_marked": [{"id": e.id, "employee_code": e.employee_code, "name": e.name, "role": e.role}
                           for e in unmarked],
        }

    async def monthly(self, scope: BranchScope, employee_id: UUID | None, month: int | None,
                      year: int | None) -> dict:
        today = timeutil.today()
        month, year = month or today.month, year or today.year
        if employee_id:
            await self._require_employee(employee_id, scope)
        start, end = timeutil.month_bounds(year, month)
        rows = await self._repo.list_for_range(scope, start, end, employee_id)
        counts = {s: 0 for s in AttendanceStatus}
        for row in rows:
            counts[row[0].status] += 1
        return {
            "employee_id": employee_id,
            "month_year": timeutil.month_key(year, month),
            "records": [self.attendance_out(*r) for r in rows],
            "summary": {"present": counts[AttendanceStatus.PRESENT], "absent": counts[AttendanceStatus.ABSENT],
                        "late": counts[AttendanceStatus.LATE], "half_day": counts[AttendanceStatus.HALF_DAY],
                        "on_leave": counts[AttendanceStatus.ON_LEAVE], "total_days_in_month": end.day},
        }

    # ── commands ─────────────────────────────────────────────────────────
    async def mark(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        today = timeutil.today()
        day = data.date or today
        if day > today:
            raise BadRequestError("Attendance cannot be marked for a future date")
        employee = await self._require_employee(data.employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("Cannot mark attendance for a terminated employee")
        attendance = await self._repo.get_for_employee_date(employee.id, day, scope)
        if attendance is None:
            attendance = await self._repo.add(Attendance(
                organization_id=employee.organization_id, branch_id=employee.branch_id,
                employee_id=employee.id, attendance_date=day, status=data.status, created_by=actor.user_id))
        attendance.status = data.status
        attendance.notes = data.notes
        if data.status in _CHECK_IN_STATUSES and attendance.check_in_time is None and day == today:
            attendance.check_in_time = timeutil.now_time()
        attendance.updated_by = actor.user_id
        await self._repo.commit()
        return await self._row_out(attendance.id, scope)

    async def checkout(self, employee_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        employee = await self._require_employee(employee_id, scope)
        attendance = await self._repo.get_for_employee_date(employee.id, timeutil.today(), scope)
        if attendance is None or attendance.check_in_time is None:
            raise BadRequestError("No check-in found for today. Mark check-in first")
        if attendance.check_out_time is not None:
            raise BadRequestError("Employee has already checked out today")
        attendance.check_out_time = timeutil.now_time()
        attendance.updated_by = actor.user_id
        await self._repo.commit()
        return await self._row_out(attendance.id, scope)
