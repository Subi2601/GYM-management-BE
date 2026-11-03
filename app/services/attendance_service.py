"""Attendance business logic.

Staff keep one day record per employee (status + first in / last out — payroll reads it). Every visit, staff or
member, is also an `AttendanceSession` (check-in → check-out, several per day), whether marked at the front desk
(MANUAL) or by scanning the branch QR (QR). `check_in` / `check_out` below are shared by both paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import AttendancePersonType, AttendanceSource, AttendanceStatus, EmployeeStatus
from app.core.scope import BranchScope
from app.models.attendance import AttendanceSession
from app.models.member import Member
from app.models.staff import Attendance, Employee
from app.repositories.attendance_repository import AttendanceRepository
from app.repositories.attendance_session_repository import AttendanceSessionRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.member_repository import MemberRepository

_CHECK_IN_STATUSES = (AttendanceStatus.PRESENT, AttendanceStatus.LATE)
# A staff member is late when the day's first check-in is more than this after their shift starts.
LATE_GRACE = timedelta(minutes=10)


def clock(t: time) -> str:
    """06:42:00 → "6:42 AM" (how times read in messages)."""
    return t.strftime("%I:%M %p").lstrip("0")


def minutes_between(start: time, end: time) -> int:
    return max(0, int((datetime.combine(date.min, end) - datetime.combine(date.min, start)).total_seconds() // 60))


def is_late(employee: Employee, at: time) -> bool:
    """First check-in vs the shift it falls in: the morning shift until it ends, otherwise the evening shift."""
    def with_grace(t: time) -> time:
        return (datetime.combine(date.min, t) + LATE_GRACE).time()

    if employee.morning_start and (employee.morning_end is None or at < employee.morning_end):
        return at > with_grace(employee.morning_start)
    if employee.evening_start:
        return at > with_grace(employee.evening_start)
    return False


@dataclass(frozen=True)
class Person:
    """Who is checking in — a staff member or a gym member."""
    type: AttendancePersonType
    employee: Employee | None = None
    member: Member | None = None

    @property
    def id(self) -> UUID:
        return self.employee.id if self.employee else self.member.id  # type: ignore[union-attr]

    @property
    def name(self) -> str:
        return self.employee.name if self.employee else self.member.name  # type: ignore[union-attr]

    @property
    def organization_id(self) -> UUID:
        return (self.employee or self.member).organization_id  # type: ignore[union-attr]

    @property
    def branch_id(self) -> UUID:
        return (self.employee or self.member).branch_id  # type: ignore[union-attr]

    @staticmethod
    def staff(employee: Employee) -> "Person":
        return Person(AttendancePersonType.STAFF, employee=employee)

    @staticmethod
    def of_member(member: Member) -> "Person":
        return Person(AttendancePersonType.MEMBER, member=member)


class AttendanceService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = AttendanceRepository(db)
        self._sessions = AttendanceSessionRepository(db)
        self._employees = EmployeeRepository(db)
        self._members = MemberRepository(db)

    # ── output builders ──────────────────────────────────────────────────
    @staticmethod
    def attendance_out(a: Attendance, name: str, code: str, role,
                       sessions: list[AttendanceSession] | None = None) -> dict:
        sessions = sessions or []
        return {"id": a.id, "branch_id": a.branch_id, "employee_id": a.employee_id, "employee_name": name,
                "employee_code": code, "employee_role": role, "attendance_date": a.attendance_date,
                "check_in_time": a.check_in_time, "check_out_time": a.check_out_time, "status": a.status,
                "notes": a.notes, "created_at": a.created_at, "updated_at": a.updated_at,
                "inside": any(s.check_out_time is None for s in sessions),
                "visits": len(sessions),
                "worked_minutes": sum(minutes_between(s.check_in_time, s.check_out_time)
                                      for s in sessions if s.check_out_time),
                "source": sessions[0].in_source if sessions else None}

    @staticmethod
    def member_session_out(s: AttendanceSession, name: str, registration_id: str, phone: str) -> dict:
        return {"id": s.id, "member_id": s.member_id, "member_name": name, "registration_id": registration_id,
                "phone": phone, "session_date": s.session_date, "check_in_time": s.check_in_time,
                "check_out_time": s.check_out_time, "in_source": s.in_source, "out_source": s.out_source,
                "denied_reason": s.denied_reason,
                "duration_minutes": minutes_between(s.check_in_time, s.check_out_time) if s.check_out_time else None}

    async def _require_employee(self, employee_id: UUID, scope: BranchScope) -> Employee:
        employee = await self._employees.get_employee(employee_id, scope)
        if employee is None:
            raise NotFoundError("Employee")
        return employee

    async def _require_member(self, member_id: UUID, scope: BranchScope) -> Member:
        member = await self._sessions.get_member(member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        return member

    async def _row_out(self, attendance_id: UUID, scope: BranchScope) -> dict:
        a, name, code, role = await self._repo.get_row(attendance_id, scope)
        sessions = await self._sessions.staff_sessions(scope, a.attendance_date, [a.employee_id])
        return self.attendance_out(a, name, code, role, sessions)

    # ── queries ──────────────────────────────────────────────────────────
    async def daily(self, scope: BranchScope, day: date | None) -> dict:
        day = day or timeutil.today()
        records = await self._repo.list_for_date(scope, day)
        unmarked = await self._repo.unmarked_active_employees(scope, day)
        by_employee: dict[UUID, list[AttendanceSession]] = {}
        for s in await self._sessions.staff_sessions(scope, day):
            by_employee.setdefault(s.employee_id, []).append(s)  # type: ignore[arg-type]
        return {
            "date": day,
            "records": [self.attendance_out(*r, by_employee.get(r[0].employee_id)) for r in records],
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

    async def members_daily(self, scope: BranchScope, day: date | None) -> dict:
        day = day or timeutil.today()
        rows = await self._sessions.member_sessions(scope, day)
        records = [self.member_session_out(*r) for r in rows]
        accepted = [r for r in records if r["denied_reason"] is None]
        return {
            "date": day,
            "records": records,
            "summary": {"inside": sum(1 for r in accepted if r["check_out_time"] is None),
                        "checked_in": len({r["member_id"] for r in accepted}),
                        "visits": len(accepted),
                        "denied": len(records) - len(accepted)},
        }

    # ── shared check-in / check-out (front desk + QR) ────────────────────
    async def check_in(self, person: Person, scope: BranchScope, source: AttendanceSource,
                       actor_id: UUID | None) -> dict:
        """Starts a session. Raises 400 with a message meant for the person (QR) or the front desk (manual)."""
        today, now = timeutil.today(), timeutil.now_time()
        qr = source == AttendanceSource.QR
        if person.member is not None:
            end = await self._members.membership_end(person.member.id)
            if end is None or end < today:
                reason = "No active membership" if end is None else "Membership expired"
                if qr:   # kept on the attendance list so the front desk can follow up
                    await self._sessions.add(self._session(person, today, now, source, actor_id, denied=reason))
                    await self._sessions.commit()
                    raise BadRequestError(f"{reason}. Contact the front desk to renew.")
                raise BadRequestError(f"{reason} for {person.name}. Renew the membership to check in.")
        if person.employee is not None and person.employee.status == EmployeeStatus.INACTIVE:
            raise BadRequestError("Your staff account is inactive. Contact the manager." if qr
                                  else f"{person.name} is inactive. Change the status to mark attendance.")

        current = await self._sessions.open_session(person.type, person.id, today, scope)
        if current is not None:
            since = clock(current.check_in_time)
            raise BadRequestError(f"You're already checked in since {since}. Scan CHECK OUT when you leave." if qr
                                  else f"{person.name} is already checked in since {since}")

        await self._sessions.add(self._session(person, today, now, source, actor_id))
        late = False
        if person.employee is not None:
            late = await self._staff_day_in(person.employee, today, now, actor_id)
        await self._sessions.commit()
        return {"direction": "IN", "person_type": person.type, "name": person.name, "time": now, "late": late,
                "duration_minutes": None}

    async def check_out(self, person: Person, scope: BranchScope, source: AttendanceSource,
                        actor_id: UUID | None) -> dict:
        today, now = timeutil.today(), timeutil.now_time()
        current = await self._sessions.open_session(person.type, person.id, today, scope)
        if current is None:
            raise BadRequestError("You haven't checked in today. Scan the CHECK IN QR first."
                                  if source == AttendanceSource.QR else f"{person.name} hasn't checked in today")
        self._close(current, now, source, actor_id)
        if person.employee is not None:
            await self._staff_day_out(person.employee.id, today, now, scope, actor_id)
        await self._sessions.commit()
        return {"direction": "OUT", "person_type": person.type, "name": person.name, "time": now, "late": False,
                "duration_minutes": minutes_between(current.check_in_time, now)}

    @staticmethod
    def _session(person: Person, day: date, at: time, source: AttendanceSource, actor_id: UUID | None,
                 denied: str | None = None) -> AttendanceSession:
        return AttendanceSession(
            organization_id=person.organization_id, branch_id=person.branch_id, person_type=person.type,
            employee_id=person.employee.id if person.employee else None,
            member_id=person.member.id if person.member else None,
            session_date=day, check_in_time=at, in_source=source, denied_reason=denied, created_by=actor_id)

    @staticmethod
    def _close(session: AttendanceSession, at: time, source: AttendanceSource, actor_id: UUID | None) -> None:
        session.check_out_time = at
        session.out_source = source
        session.updated_by = actor_id

    async def _staff_day_in(self, employee: Employee, day: date, at: time, actor_id: UUID | None) -> bool:
        """Keeps the day record in step with a check-in. Returns True when this check-in made the day LATE."""
        scope = BranchScope(employee.organization_id, employee.branch_id, (employee.branch_id,))
        attendance = await self._repo.get_for_employee_date(employee.id, day, scope)
        late = False
        if attendance is None:
            late = is_late(employee, at)
            await self._repo.add(Attendance(
                organization_id=employee.organization_id, branch_id=employee.branch_id, employee_id=employee.id,
                attendance_date=day, check_in_time=at,
                status=AttendanceStatus.LATE if late else AttendanceStatus.PRESENT, created_by=actor_id))
            return late
        if attendance.check_in_time is None:
            attendance.check_in_time = at
            if attendance.status not in (*_CHECK_IN_STATUSES, AttendanceStatus.HALF_DAY):   # was absent / leave
                late = is_late(employee, at)
                attendance.status = AttendanceStatus.LATE if late else AttendanceStatus.PRESENT
        attendance.check_out_time = None        # back inside
        attendance.updated_by = actor_id
        return late

    async def _staff_day_out(self, employee_id: UUID, day: date, at: time, scope: BranchScope,
                             actor_id: UUID | None) -> None:
        attendance = await self._repo.get_for_employee_date(employee_id, day, scope)
        if attendance is not None:
            attendance.check_out_time = at
            attendance.updated_by = actor_id

    # ── front-desk commands ──────────────────────────────────────────────
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
            # Marked present at the desk = they're in now: open a session like a check-in would.
            person = Person.staff(employee)
            if await self._sessions.open_session(person.type, person.id, today, scope) is None:
                await self._sessions.add(self._session(person, today, attendance.check_in_time,
                                                       AttendanceSource.MANUAL, actor.user_id))
        attendance.updated_by = actor.user_id
        await self._repo.commit()
        return await self._row_out(attendance.id, scope)

    async def checkout(self, employee_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        employee = await self._require_employee(employee_id, scope)
        today = timeutil.today()
        attendance = await self._repo.get_for_employee_date(employee.id, today, scope)
        if attendance is None or attendance.check_in_time is None:
            raise BadRequestError("No check-in found for today. Mark check-in first")
        person = Person.staff(employee)
        if await self._sessions.open_session(person.type, person.id, today, scope) is not None:
            await self.check_out(person, scope, AttendanceSource.MANUAL, actor.user_id)
        elif attendance.check_out_time is not None:
            raise BadRequestError("Employee has already checked out today")
        else:   # day marked before sessions existed
            attendance.check_out_time = timeutil.now_time()
            attendance.updated_by = actor.user_id
            await self._repo.commit()
        return await self._row_out(attendance.id, scope)

    async def member_check_in(self, member_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        member = await self._require_member(member_id, scope)
        return await self.check_in(Person.of_member(member), scope, AttendanceSource.MANUAL, actor.user_id)

    async def member_check_out(self, member_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        member = await self._require_member(member_id, scope)
        return await self.check_out(Person.of_member(member), scope, AttendanceSource.MANUAL, actor.user_id)

    async def close_session(self, session_id: UUID, at: time | None, scope: BranchScope,
                            actor: RequestContext) -> None:
        """Front desk closes a visit — today's at `at` or now; a past day's (forgot to check out) needs `at`."""
        scope.require_branch()
        session = await self._sessions.get_session(session_id, scope)
        if session is None:
            raise NotFoundError("Attendance session")
        if session.denied_reason is not None:
            raise BadRequestError("This check-in was refused, there is nothing to close")
        if session.check_out_time is not None:
            raise BadRequestError("This visit is already checked out")
        today = timeutil.today()
        if at is None:
            if session.session_date != today:
                raise BadRequestError("Enter the check-out time for a past day")
            at = timeutil.now_time()
        at = at.replace(microsecond=0)
        if at < session.check_in_time.replace(second=0):
            raise BadRequestError(f"Check-out time must be after the check-in at {clock(session.check_in_time)}")
        at = max(at, session.check_in_time)   # same minute as the check-in (HH:MM input)
        if session.session_date == today and at > timeutil.now_time():
            raise BadRequestError("Check-out time cannot be in the future")
        self._close(session, at, AttendanceSource.MANUAL, actor.user_id)
        if session.employee_id is not None:
            await self._staff_day_out(session.employee_id, session.session_date, at, scope, actor.user_id)
        await self._sessions.commit()
