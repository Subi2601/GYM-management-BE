"""DB operations for monthly salaries. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.core.scope import BranchScope
from app.models.staff import Employee, Salary
from app.repositories.base import BaseRepository


class SalaryRepository(BaseRepository):

    def _joined(self, scope: BranchScope):
        """(Salary, employee name, code, role) — scoped on the salary row."""
        stmt = (select(Salary, Employee.name, Employee.employee_code, Employee.role)
                .join(Employee, Employee.id == Salary.employee_id))
        return self.scoped(Salary, stmt, scope)

    async def list_for_month(self, scope: BranchScope, month_year: str) -> list:
        stmt = self._joined(scope).where(Salary.month_year == month_year).order_by(Employee.employee_code.asc())
        return list((await self._db.execute(stmt)).all())

    async def list_for_employee(self, scope: BranchScope, employee_id: UUID) -> list:
        # month_year is MM-YYYY → order by year then month
        stmt = (self._joined(scope).where(Salary.employee_id == employee_id)
                .order_by(func.substring(Salary.month_year, 4, 4).desc(),
                          func.substring(Salary.month_year, 1, 2).desc()))
        return list((await self._db.execute(stmt)).all())

    async def get_row(self, salary_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._joined(scope).where(Salary.id == salary_id))).first()

    async def get_salary(self, salary_id: UUID, scope: BranchScope) -> Salary | None:
        return await self.get_scoped(Salary, salary_id, scope)

    async def for_employees_month(self, scope: BranchScope, employee_ids: list[UUID],
                                  month_year: str) -> dict[UUID, Salary]:
        if not employee_ids:
            return {}
        stmt = self.scoped(Salary, select(Salary).where(Salary.employee_id.in_(employee_ids),
                                                        Salary.month_year == month_year), scope)
        return {s.employee_id: s for s in (await self._db.execute(stmt)).scalars().all()}
