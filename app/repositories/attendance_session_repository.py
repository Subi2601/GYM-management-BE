"""DB operations for attendance sessions, linked check-in phones and QR branch lookups. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import or_, select, update

from app.core.enums import AttendancePersonType, EmployeeStatus
from app.core.scope import BranchScope
from app.models.attendance import AttendanceDevice, AttendanceSession
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
        stmt = (select(AttendanceSession, Member.name, Member.registration_id, Member.phone)
                .join(Member, Member.id == AttendanceSession.member_id)
                .where(AttendanceSession.person_type == AttendancePersonType.MEMBER, Member.is_delete.is_(False)))
        return self.scoped(AttendanceSession, stmt, scope)

    async def member_sessions(self, scope: BranchScope, day: date) -> list:
        """Rows (session, member name, registration id, phone) of `day`, newest check-in first."""
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

    async def devices_of(self, person_type: AttendancePersonType, person_id: UUID) -> list[AttendanceDevice]:
        stmt = self.alive(AttendanceDevice, select(AttendanceDevice).where(
            _person_filter(AttendanceDevice, person_type, person_id)))
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
