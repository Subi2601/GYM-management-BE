"""DB operations for employees, their client feedback and the PT clients they train. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import Integer, cast, func, or_, select

from app.core.enums import EmployeeRole, EmployeeStatus
from app.core.scope import BranchScope
from app.models.billing import Plan
from app.models.member import Member
from app.models.staff import Employee, EmployeeFeedback
from app.models.training import PTSubscription
from app.repositories.base import BaseRepository

_CODE_PREFIX = "SG-EMP-"


class EmployeeRepository(BaseRepository):

    # ── employees ────────────────────────────────────────────────────────
    async def list_employees(self, scope: BranchScope, *, offset: int, limit: int,
                             statuses: tuple[EmployeeStatus, ...] | None = None,
                             role: EmployeeRole | None = None,
                             search: str | None = None, sort_by: str | None = None,
                             sort_dir: str = "desc") -> tuple[list[Employee], int]:
        stmt = self.scoped(Employee, select(Employee), scope)
        if statuses:
            stmt = stmt.where(Employee.status.in_(statuses))
        if role:
            stmt = stmt.where(Employee.role == role)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Employee.name.ilike(pattern), Employee.employee_code.ilike(pattern),
                                  Employee.phone.ilike(pattern)))
        columns = {"employee_code": Employee.employee_code, "name": Employee.name, "role": Employee.role,
                   "base_salary": Employee.base_salary, "date_of_joining": Employee.date_of_joining,
                   "average_rating": Employee.average_rating, "created_at": Employee.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir, (Employee.employee_code.asc(),), Employee.id)
        return await self.paginate_scalars(stmt, offset=offset, limit=limit)

    async def status_counts(self, scope: BranchScope,
                            groups: dict[str, tuple[EmployeeStatus, ...] | None]) -> dict[str, int]:
        """One count per status group (None = every employee)."""
        return await self.count_tabs(self.scoped(Employee, select(Employee), scope), {
            key: None if statuses is None else Employee.status.in_(statuses) for key, statuses in groups.items()})

    async def get_employee(self, employee_id: UUID, scope: BranchScope) -> Employee | None:
        return await self.get_scoped(Employee, employee_id, scope)

    async def get_by_phone(self, branch_id: UUID, phone: str) -> Employee | None:
        stmt = select(Employee).where(Employee.branch_id == branch_id, Employee.phone == phone)
        return (await self._db.execute(stmt)).scalars().first()

    async def last_code_number(self, branch_id: UUID) -> int:
        """Highest numeric suffix of SG-EMP-### codes in the branch (terminated / deleted rows included)."""
        num = cast(func.substring(Employee.employee_code, len(_CODE_PREFIX) + 1), Integer)
        stmt = select(func.max(num)).where(Employee.branch_id == branch_id,
                                           Employee.employee_code.op("~")(r"^SG-EMP-\d+$"))
        return (await self._db.execute(stmt)).scalar_one() or 0

    async def list_by_status(self, scope: BranchScope, status: EmployeeStatus,
                             role: EmployeeRole | None = None) -> list[Employee]:
        stmt = self.scoped(Employee, select(Employee).where(Employee.status == status), scope)
        if role:
            stmt = stmt.where(Employee.role == role)
        return list((await self._db.execute(stmt.order_by(Employee.name.asc()))).scalars().all())

    # ── feedback ─────────────────────────────────────────────────────────
    async def list_feedbacks(self, employee_id: UUID, scope: BranchScope) -> list[EmployeeFeedback]:
        stmt = self.scoped(EmployeeFeedback, select(EmployeeFeedback)
                           .where(EmployeeFeedback.employee_id == employee_id), scope)
        stmt = stmt.order_by(EmployeeFeedback.feedback_date.desc(), EmployeeFeedback.created_at.desc())
        return list((await self._db.execute(stmt)).scalars().all())

    async def average_rating(self, employee_id: UUID, scope: BranchScope) -> float | None:
        stmt = self.scoped(EmployeeFeedback, select(func.avg(EmployeeFeedback.rating))
                           .where(EmployeeFeedback.employee_id == employee_id), scope)
        value = (await self._db.execute(stmt)).scalar_one()
        return float(value) if value is not None else None

    # ── PT clients (employee as trainer) ─────────────────────────────────
    async def list_pt_clients(self, trainer_id: UUID, scope: BranchScope) -> list:
        """Rows: (PTSubscription, member_name, plan_name)."""
        stmt = (select(PTSubscription, Member.name.label("member_name"), Plan.name.label("plan_name"))
                .join(Member, Member.id == PTSubscription.member_id)
                .outerjoin(Plan, Plan.id == PTSubscription.plan_id)
                .where(PTSubscription.trainer_id == trainer_id))
        stmt = self.scoped(PTSubscription, stmt, scope)
        stmt = stmt.order_by(PTSubscription.start_date.desc(), PTSubscription.created_at.desc())
        return list((await self._db.execute(stmt)).all())
