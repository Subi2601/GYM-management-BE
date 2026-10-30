"""DB operations for staff attendance. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import and_, func, select

from app.core.enums import AttendanceStatus, EmployeeStatus
from app.core.scope import BranchScope
from app.models.staff import Attendance, Employee
from app.repositories.base import BaseRepository


class AttendanceRepository(BaseRepository):

    def _joined(self, scope: BranchScope):
        """(Attendance, employee name, code, role) — scoped on the attendance row."""
        stmt = (select(Attendance, Employee.name, Employee.employee_code, Employee.role)
                .join(Employee, Employee.id == Attendance.employee_id)
                .where(Employee.is_delete.is_(False)))
        return self.scoped(Attendance, stmt, scope)

    async def list_for_date(self, scope: BranchScope, day: date) -> list:
        stmt = self._joined(scope).where(Attendance.attendance_date == day).order_by(Employee.name.asc())
        return list((await self._db.execute(stmt)).all())

    async def list_for_range(self, scope: BranchScope, start: date, end: date,
                             employee_id: UUID | None = None) -> list:
        stmt = self._joined(scope).where(Attendance.attendance_date.between(start, end))
        if employee_id:
            stmt = stmt.where(Attendance.employee_id == employee_id)
        stmt = stmt.order_by(Attendance.attendance_date.asc(), Employee.name.asc())
        return list((await self._db.execute(stmt)).all())

    async def get_row(self, attendance_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._joined(scope).where(Attendance.id == attendance_id))).first()

    async def get_for_employee_date(self, employee_id: UUID, day: date, scope: BranchScope) -> Attendance | None:
        stmt = self.scoped(Attendance, select(Attendance).where(Attendance.employee_id == employee_id,
                                                                Attendance.attendance_date == day), scope)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def unmarked_active_employees(self, scope: BranchScope, day: date) -> list[Employee]:
        """ACTIVE employees (joined on/before `day`) without an attendance row for `day`."""
        marked = (select(Attendance.id)
                  .where(and_(Attendance.employee_id == Employee.id, Attendance.attendance_date == day,
                              Attendance.is_delete.is_(False)))
                  .exists())
        stmt = self.scoped(Employee, select(Employee).where(Employee.status == EmployeeStatus.ACTIVE,
                                                            Employee.date_of_joining <= day, ~marked), scope)
        return list((await self._db.execute(stmt.order_by(Employee.name.asc()))).scalars().all())

    async def status_counts(self, scope: BranchScope, start: date, end: date,
                            employee_ids: list[UUID]) -> dict[UUID, dict[AttendanceStatus, int]]:
        """{employee_id: {status: days}} for the date range."""
        if not employee_ids:
            return {}
        stmt = self.scoped(Attendance, select(Attendance.employee_id, Attendance.status, func.count(Attendance.id))
                           .where(Attendance.employee_id.in_(employee_ids),
                                  Attendance.attendance_date.between(start, end)), scope)
        stmt = stmt.group_by(Attendance.employee_id, Attendance.status)
        out: dict[UUID, dict[AttendanceStatus, int]] = {}
        for emp_id, status, count in (await self._db.execute(stmt)).all():
            out.setdefault(emp_id, {})[status] = count
        return out

    async def absent_dates(self, scope: BranchScope, start: date, end: date,
                           employee_ids: list[UUID]) -> dict[UUID, list[date]]:
        if not employee_ids:
            return {}
        stmt = self.scoped(Attendance, select(Attendance.employee_id, Attendance.attendance_date)
                           .where(Attendance.employee_id.in_(employee_ids),
                                  Attendance.status == AttendanceStatus.ABSENT,
                                  Attendance.attendance_date.between(start, end)), scope)
        out: dict[UUID, list[date]] = {}
        for emp_id, day in (await self._db.execute(stmt.order_by(Attendance.attendance_date.asc()))).all():
            out.setdefault(emp_id, []).append(day)
        return out
