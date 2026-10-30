"""DB operations for personal training subscriptions, session logs and trainer lookups. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select

from app.core.enums import EmployeeRole, EmployeeStatus, PTStatus
from app.core.scope import BranchScope
from app.models.billing import Plan
from app.models.member import Member
from app.models.staff import Employee
from app.models.training import PTSessionLog, PTSubscription
from app.repositories.base import BaseRepository


class TrainingRepository(BaseRepository):

    async def get_active_trainer(self, trainer_id: UUID, branch_id: UUID) -> Employee | None:
        stmt = self.alive(Employee, select(Employee).where(
            Employee.id == trainer_id, Employee.branch_id == branch_id,
            Employee.role == EmployeeRole.TRAINER, Employee.status == EmployeeStatus.ACTIVE))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    async def get_plan(self, plan_id: UUID, scope: BranchScope) -> Plan | None:
        return await self.get_scoped(Plan, plan_id, scope)

    async def get_pt(self, pt_id: UUID, scope: BranchScope, *, for_update: bool = False) -> PTSubscription | None:
        stmt = self.scoped(PTSubscription, select(PTSubscription).where(PTSubscription.id == pt_id), scope)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._db.execute(stmt)).scalar_one_or_none()

    # ── joined reads ─────────────────────────────────────────────────────
    def _row_stmt(self, scope: BranchScope):
        """Rows: (PTSubscription, member_name, registration_id, member_phone, trainer_name, plan_name)."""
        stmt = (select(PTSubscription, Member.name, Member.registration_id, Member.phone, Employee.name, Plan.name)
                .join(Member, Member.id == PTSubscription.member_id)
                .outerjoin(Employee, Employee.id == PTSubscription.trainer_id)
                .outerjoin(Plan, Plan.id == PTSubscription.plan_id))
        return self.scoped(PTSubscription, stmt, scope)

    async def list_pt(self, scope: BranchScope, *, offset: int, limit: int, status: PTStatus | None,
                      paid_only: bool, search: str | None, trainer_id: UUID | None,
                      member_id: UUID | None) -> tuple[list, int]:
        stmt = self._row_stmt(scope).where(Member.is_delete.is_(False))
        if status is not None:
            stmt = stmt.where(PTSubscription.status == status)
        if paid_only:
            stmt = stmt.where(PTSubscription.is_paid.is_(True))
        if trainer_id:
            stmt = stmt.where(PTSubscription.trainer_id == trainer_id)
        if member_id:
            stmt = stmt.where(PTSubscription.member_id == member_id)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Member.name.ilike(pattern), Member.phone.ilike(pattern),
                                  Member.registration_id.ilike(pattern), Employee.name.ilike(pattern),
                                  Plan.name.ilike(pattern)))
        stmt = stmt.order_by(PTSubscription.start_date.desc(), PTSubscription.created_at.desc())
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def get_pt_row(self, pt_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._row_stmt(scope).where(PTSubscription.id == pt_id))).first()

    async def list_sessions(self, pt_id: UUID, scope: BranchScope) -> list:
        """Rows: (PTSessionLog, trainer_name)."""
        stmt = (self.scoped(PTSessionLog, select(PTSessionLog, Employee.name)
                            .outerjoin(Employee, Employee.id == PTSessionLog.trainer_id)
                            .where(PTSessionLog.pt_subscription_id == pt_id), scope)
                .order_by(PTSessionLog.session_date.desc(), PTSessionLog.created_at.desc()))
        return list((await self._db.execute(stmt)).all())
