"""Payroll business logic — monthly salary from attendance, bulk calculation, payment."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import AttendanceStatus, EmployeeStatus, SalaryStatus
from app.core.scope import BranchScope
from app.models.staff import Salary
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.salary_repository import SalaryRepository

_CENT = Decimal("0.01")
OUTCOME_CALCULATED = "CALCULATED"
OUTCOME_SKIPPED_PAID = "SKIPPED_PAID"


def _round(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def compute_salary(base: Decimal, days_in_month: int, present: int, absent: int) -> dict[str, Decimal]:
    """Original rule: per-day = base / days-in-month; deductions = per-day × absent;
    till-now = per-day × present; net = base − deductions. Rounded to 2 dp."""
    base = Decimal(base or 0)
    per_day = base / Decimal(days_in_month)
    deductions = _round(per_day * absent)
    return {"base_salary": _round(base), "deductions": deductions,
            "till_now_salary": _round(per_day * present), "net_salary": _round(base - deductions)}


def _parse_month_year(month_year: str) -> tuple[int, int]:
    month, year = month_year.split("-")
    return int(month), int(year)


class SalaryService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = SalaryRepository(db)
        self._attendance = AttendanceRepository(db)
        self._employees = EmployeeRepository(db)

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def salary_out(s: Salary, name: str, code: str, role, absent_dates: list) -> dict:
        return {
            "id": s.id, "branch_id": s.branch_id, "employee_id": s.employee_id, "employee_name": name,
            "employee_code": code, "employee_role": role, "month_year": s.month_year,
            "base_salary": float(s.base_salary), "days_present": s.days_present, "days_absent": s.days_absent,
            "days_late": s.days_late, "deductions": float(s.deductions), "bonus": float(s.bonus),
            "till_now_salary": float(s.till_now_salary), "net_salary": float(s.net_salary),
            "status": s.status, "paid_date": s.paid_date, "payment_method": s.payment_method,
            "absent_dates": absent_dates, "created_at": s.created_at, "updated_at": s.updated_at,
        }

    async def _rows_out(self, rows: list, scope: BranchScope) -> list[dict]:
        """Attach the ABSENT dates of each salary month (one query per distinct month)."""
        by_month: dict[str, list[UUID]] = {}
        for row in rows:
            by_month.setdefault(row[0].month_year, []).append(row[0].employee_id)
        absent: dict[tuple[str, UUID], list] = {}
        for month_year, employee_ids in by_month.items():
            month, year = _parse_month_year(month_year)
            start, end = timeutil.month_bounds(year, month)
            for emp_id, dates in (await self._attendance.absent_dates(scope, start, end, employee_ids)).items():
                absent[(month_year, emp_id)] = dates
        return [self.salary_out(*row, absent.get((row[0].month_year, row[0].employee_id), [])) for row in rows]

    # ── queries ──────────────────────────────────────────────────────────
    async def list_for_month(self, scope: BranchScope, month: int | None, year: int | None) -> dict:
        today = timeutil.today()
        month, year = month or today.month, year or today.year
        month_year = timeutil.month_key(year, month)
        items = await self._rows_out(await self._repo.list_for_month(scope, month_year), scope)
        total = sum((Decimal(str(i["net_salary"])) for i in items), Decimal("0"))
        return {"month_year": month_year, "items": items, "total_payout": float(_round(total))}

    async def employee_history(self, employee_id: UUID, scope: BranchScope) -> list[dict]:
        if await self._employees.get_employee(employee_id, scope) is None:
            raise NotFoundError("Employee")
        return await self._rows_out(await self._repo.list_for_employee(scope, employee_id), scope)

    # ── commands ─────────────────────────────────────────────────────────
    async def calculate(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        """Single employee (any status, e.g. final settlement) or every ACTIVE employee of the branch.
        Existing PENDING rows are recalculated; PAID rows are never touched."""
        branch_id = scope.require_branch()
        branch_scope = BranchScope(scope.organization_id, branch_id, (branch_id,))
        if data.employee_id:
            employee = await self._employees.get_employee(data.employee_id, branch_scope)
            if employee is None:
                raise NotFoundError("Employee")
            employees = [employee]
        else:
            employees = await self._employees.list_by_status(branch_scope, EmployeeStatus.ACTIVE)
            if not employees:
                raise BadRequestError("No active employees in this branch")

        month_year = timeutil.month_key(data.year, data.month)
        start, end = timeutil.month_bounds(data.year, data.month)
        ids = [e.id for e in employees]
        counts = await self._attendance.status_counts(branch_scope, start, end, ids)
        existing = await self._repo.for_employees_month(branch_scope, ids, month_year)

        outcomes: list[tuple] = []
        for employee in employees:
            salary = existing.get(employee.id)
            if salary is not None and salary.status == SalaryStatus.PAID:
                outcomes.append((employee, salary, OUTCOME_SKIPPED_PAID))
                continue
            days = counts.get(employee.id, {})
            present = days.get(AttendanceStatus.PRESENT, 0)
            absent = days.get(AttendanceStatus.ABSENT, 0)
            late = days.get(AttendanceStatus.LATE, 0)
            if salary is None:
                salary = await self._repo.add(Salary(
                    organization_id=employee.organization_id, branch_id=employee.branch_id,
                    employee_id=employee.id, month_year=month_year, base_salary=0, created_by=actor.user_id))
            for field, value in compute_salary(employee.base_salary, end.day, present, absent).items():
                setattr(salary, field, value)
            salary.days_present, salary.days_absent, salary.days_late = present, absent, late
            salary.bonus = Decimal("0")
            salary.status = SalaryStatus.PENDING
            salary.paid_date = None
            salary.payment_method = None
            salary.updated_by = actor.user_id
            outcomes.append((employee, salary, OUTCOME_CALCULATED))
        await self._repo.commit()

        absent_dates = await self._attendance.absent_dates(branch_scope, start, end, ids)
        results = [{
            "employee_id": e.id, "employee_name": e.name, "employee_code": e.employee_code, "outcome": outcome,
            "salary": self.salary_out(s, e.name, e.employee_code, e.role, absent_dates.get(e.id, [])),
        } for e, s, outcome in outcomes]
        return {"month_year": month_year,
                "calculated": sum(1 for *_, o in outcomes if o == OUTCOME_CALCULATED),
                "skipped_paid": sum(1 for *_, o in outcomes if o == OUTCOME_SKIPPED_PAID),
                "results": results}

    async def pay(self, salary_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        salary = await self._repo.get_salary(salary_id, scope)
        if salary is None:
            raise NotFoundError("Salary record")
        if salary.status == SalaryStatus.PAID:
            raise ConflictError("Salary is already paid")
        salary.status = SalaryStatus.PAID
        salary.paid_date = data.paid_date or timeutil.today()
        salary.payment_method = data.payment_method
        salary.updated_by = actor.user_id
        await self._repo.commit()
        return (await self._rows_out([await self._repo.get_row(salary.id, scope)], scope))[0]
