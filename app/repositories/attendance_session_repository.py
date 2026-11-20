"""DB operations for attendance sessions, linked check-in phones and QR branch lookups. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select, update

from app.core.enums import MEMBERSHIP_PLAN_TYPES, AttendancePersonType, EmployeeStatus
from app.core.scope import BranchScope
from app.models.attendance import AttendanceDevice, AttendanceSession
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.models.organization import Branch
from app.models.staff import Employee
from app.repositories.base import BaseRepository


def _person_filter(model, person_type: AttendancePersonType, person_id: UUID):
    column = model.employee_id if person_type == AttendancePersonType.STAFF else model.member_id
    return column == person_id


class AttendanceSessionRepository(BaseRepository):

    # ── sessions ─────────────────────────────────────────────────────────
    async def open_session(self, person_type: AttendancePersonType, person_id: UUID, day: date,
                           scope: BranchScope) -> AttendanceSession | None:
        """Today's session still inside (checked in, not out, not refused)."""
        stmt = self.scoped(AttendanceSession, select(AttendanceSession).where(
            _person_filter(AttendanceSession, person_type, person_id),
            AttendanceSession.session_date == day, AttendanceSession.check_out_time.is_(None),
            AttendanceSession.denied_reason.is_(None)), scope)
        stmt = stmt.order_by(AttendanceSession.check_in_time.desc()).limit(1)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_session(self, session_id: UUID, scope: BranchScope) -> AttendanceSession | None:
        return await self.get_scoped(AttendanceSession, session_id, scope)

    async def staff_sessions(self, scope: BranchScope, day: date,
                             employee_ids: list[UUID] | None = None) -> list[AttendanceSession]:
        """Accepted staff sessions of `day`, oldest first."""
        stmt = self.scoped(AttendanceSession, select(AttendanceSession).where(
            AttendanceSession.person_type == AttendancePersonType.STAFF, AttendanceSession.session_date == day,
            AttendanceSession.denied_reason.is_(None)), scope)
        if employee_ids is not None:
            stmt = stmt.where(AttendanceSession.employee_id.in_(employee_ids))
        return list((await self._db.execute(stmt.order_by(AttendanceSession.check_in_time.asc()))).scalars().all())

    def _member_rows(self, scope: BranchScope):
        home_branch = aliased(Branch, name="home_branch")
        visit_branch = aliased(Branch, name="visit_branch")
        stmt = (select(AttendanceSession, Member.name, Member.registration_id, Member.phone,
                       Member.branch_id.label("home_branch_id"), home_branch.branch_name.label("home_branch"),
                       AttendanceSession.branch_id.label("attendance_branch_id"),
                       visit_branch.branch_name.label("attendance_branch"))
                .join(Member, Member.id == AttendanceSession.member_id)
                .join(home_branch, home_branch.id == Member.branch_id)
                .join(visit_branch, visit_branch.id == AttendanceSession.branch_id)
                .where(AttendanceSession.person_type == AttendancePersonType.MEMBER, Member.is_delete.is_(False)))
        return self.scoped(AttendanceSession, stmt, scope)

    async def member_sessions(self, scope: BranchScope, day: date) -> list:
        """Member visits with home and check-in branches, newest check-in first."""
        stmt = self._member_rows(scope).where(AttendanceSession.session_date == day)
        stmt = stmt.order_by(AttendanceSession.check_in_time.desc(), AttendanceSession.created_at.desc())
        return list((await self._db.execute(stmt)).all())

    async def member_session_row(self, session_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._member_rows(scope).where(AttendanceSession.id == session_id))).first()

    # ── people ───────────────────────────────────────────────────────────
    async def staff_by_phone(self, branch_id: UUID, phone: str) -> Employee | None:
        stmt = self.alive(Employee, select(Employee).where(
            Employee.branch_id == branch_id, Employee.phone == phone, Employee.status != EmployeeStatus.TERMINATED))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def member_by_phone(self, branch_id: UUID, phone: str) -> Member | None:
        stmt = self.alive(Member, select(Member).where(Member.branch_id == branch_id, Member.phone == phone))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_employee(self, employee_id: UUID, scope: BranchScope) -> Employee | None:
        return await self.get_scoped(Employee, employee_id, scope)

    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    # ── members visiting from another branch ──────────────────────────────
    def _visitors(self, organization_id: UUID, today: date):
        """Members whose latest membership is still running, regardless of which branch sold the plan."""
        rn = func.row_number().over(partition_by=Subscription.member_id,
                                    order_by=(Subscription.start_date.desc(), Subscription.created_at.desc()))
        latest = (select(Subscription.member_id, Subscription.end_date, rn.label("rn"))
                  .join(Plan, Plan.id == Subscription.plan_id)
                  .where(Subscription.organization_id == organization_id, Subscription.is_delete.is_(False),
                         Plan.type.in_(MEMBERSHIP_PLAN_TYPES))
                  .subquery())
        return (select(Member).join(latest, latest.c.member_id == Member.id)
                .where(latest.c.rn == 1, latest.c.end_date >= today,
                       Member.organization_id == organization_id, Member.is_delete.is_(False)))

    async def visitor(self, organization_id: UUID, member_id: UUID, today: date) -> Member | None:
        stmt = self._visitors(organization_id, today).where(Member.id == member_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def visitors_by_phone(self, organization_id: UUID, branch_id: UUID, phone: str,
                                today: date) -> list[Member]:
        stmt = self._visitors(organization_id, today).where(
            Member.phone == phone, Member.branch_id != branch_id)
        return list((await self._db.execute(stmt.order_by(Member.registration_id))).scalars().all())

    async def visitors_for_branch(self, organization_id: UUID, branch_id: UUID, today: date) -> list:
        """Members with a current membership who may check in here from another home branch."""
        stmt = (self._visitors(organization_id, today).add_columns(Branch.branch_name)
                .join(Branch, Branch.id == Member.branch_id).where(Member.branch_id != branch_id))
        return list((await self._db.execute(stmt.order_by(Member.name))).all())

    # ── QR branch + linked phones ────────────────────────────────────────
    async def branch_by_token(self, token: str) -> Branch | None:
        stmt = self.alive(Branch, select(Branch).where(Branch.checkin_token == token))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_branch(self, branch_id: UUID, organization_id: UUID) -> Branch | None:
        stmt = self.alive(Branch, select(Branch).where(Branch.id == branch_id,
                                                       Branch.organization_id == organization_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def set_token_if_missing(self, branch: Branch, token: str) -> None:
        """Sets the poster token only while none exists, so two first visits racing keep the same token."""
        await self._db.execute(update(Branch).where(Branch.id == branch.id, Branch.checkin_token.is_(None))
                               .values(checkin_token=token))
        await self._db.commit()
        await self._db.refresh(branch)

    async def device_by_hash(self, token_hash: str) -> AttendanceDevice | None:
        stmt = self.alive(AttendanceDevice, select(AttendanceDevice).where(AttendanceDevice.token_hash == token_hash))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def devices_of(self, person_type: AttendancePersonType, person_id: UUID,
                         branch_id: UUID | None = None) -> list[AttendanceDevice]:
        """The person's linked phones (one link works at every branch they may use); `branch_id` narrows it."""
        stmt = self.alive(AttendanceDevice, select(AttendanceDevice).where(
            _person_filter(AttendanceDevice, person_type, person_id)))
        if branch_id is not None:
            stmt = stmt.where(AttendanceDevice.branch_id == branch_id)
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_device(self, device_id: UUID, scope: BranchScope) -> AttendanceDevice | None:
        return await self.get_scoped(AttendanceDevice, device_id, scope)

    async def list_devices(self, scope: BranchScope) -> list:
        """Rows (device, staff name, staff code, member name, member registration id), last used first."""
        stmt = (select(AttendanceDevice, Employee.name, Employee.employee_code, Member.name, Member.registration_id)
                .outerjoin(Employee, Employee.id == AttendanceDevice.employee_id)
                .outerjoin(Member, Member.id == AttendanceDevice.member_id)
                .where(or_(Employee.id.is_(None), Employee.is_delete.is_(False)),
                       or_(Member.id.is_(None), Member.is_delete.is_(False))))
        stmt = self.scoped(AttendanceDevice, stmt, scope)
        stmt = stmt.order_by(AttendanceDevice.last_used_at.desc().nulls_last(), AttendanceDevice.created_at.desc())
        return list((await self._db.execute(stmt)).all())
