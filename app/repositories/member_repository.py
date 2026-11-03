"""DB operations for members. No business logic."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, Integer, and_, cast, func, or_, select

from app.core.enums import MEMBERSHIP_PLAN_TYPES, Gender
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.repositories.base import BaseRepository

EXPIRING_WINDOW_DAYS = 7
MEMBER_TABS = ("all", "active", "expiring", "inactive")


def _state_condition(end, state_filter: str | None, today: date) -> ColumnElement[bool] | None:
    """WHERE clause of a list tab on the latest membership end date; None = every member."""
    if state_filter == "active":
        return end >= today
    if state_filter == "inactive":
        return or_(end.is_(None), end < today)
    if state_filter == "expiring":
        return and_(end >= today, end <= today + timedelta(days=EXPIRING_WINDOW_DAYS))
    return None


class MemberRepository(BaseRepository):

    def _latest_membership(self):
        """Latest MEMBERSHIP subscription per member (start_date desc, created_at desc)."""
        rn = func.row_number().over(partition_by=Subscription.member_id,
                                    order_by=(Subscription.start_date.desc(), Subscription.created_at.desc()))
        inner = (select(Subscription.member_id, Subscription.plan_id, Subscription.end_date,
                        Plan.name.label("plan_name"), rn.label("rn"))
                 .join(Plan, Plan.id == Subscription.plan_id)
                 .where(Subscription.is_delete.is_(False), Plan.type.in_(MEMBERSHIP_PLAN_TYPES))
                 .subquery())
        return select(inner).where(inner.c.rn == 1).subquery()

    def _list_stmt(self, scope: BranchScope):
        latest = self._latest_membership()
        stmt = (select(Member, latest.c.plan_id, latest.c.plan_name, latest.c.end_date)
                .outerjoin(latest, latest.c.member_id == Member.id))
        return self.scoped(Member, stmt, scope), latest

    async def list_members(self, scope: BranchScope, *, offset: int, limit: int, today: date,
                           search: str | None = None, state_filter: str | None = None,
                           plan_id: UUID | None = None, gender: Gender | None = None,
                           joined_from: date | None = None, joined_to: date | None = None,
                           sort_by: str | None = None, sort_dir: str = "desc") -> tuple[list, int]:
        """Rows: (Member, plan_id, plan_name, end_date)."""
        stmt, latest = self._list_stmt(scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Member.name.ilike(pattern), Member.phone.ilike(pattern),
                                  Member.registration_id.ilike(pattern)))
        end = latest.c.end_date
        state = _state_condition(end, state_filter, today)
        if state is not None:
            stmt = stmt.where(state)
        if plan_id:
            stmt = stmt.where(latest.c.plan_id == plan_id)
        if gender:
            stmt = stmt.where(Member.gender == gender)
        if joined_from:
            stmt = stmt.where(Member.joining_date >= joined_from)
        if joined_to:
            stmt = stmt.where(Member.joining_date <= joined_to)
        columns = {"registration_id": Member.registration_id, "name": Member.name, "phone": Member.phone,
                   "joining_date": Member.joining_date, "expiry_date": end, "created_at": Member.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir, (Member.created_at.desc(),), Member.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope, today: date) -> dict[str, int]:
        stmt, latest = self._list_stmt(scope)
        return await self.count_tabs(stmt, {t: _state_condition(latest.c.end_date, t, today) for t in MEMBER_TABS})

    async def get_member_row(self, member_id: UUID, scope: BranchScope):
        stmt, _ = self._list_stmt(scope)
        return (await self._db.execute(stmt.where(Member.id == member_id))).first()

    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    async def get_by_phone(self, branch_id: UUID, phone: str) -> Member | None:
        stmt = self.alive(Member, select(Member).where(Member.branch_id == branch_id, Member.phone == phone))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def last_registration_number(self, organization_id: UUID) -> int:
        """Highest numeric suffix of SG-### registration ids in the organization (deleted rows included)."""
        num = cast(func.substring(Member.registration_id, 4), Integer)
        stmt = select(func.max(num)).where(Member.organization_id == organization_id,
                                           Member.registration_id.op("~")(r"^SG-\d+$"))
        return (await self._db.execute(stmt)).scalar_one() or 0

    async def membership_end(self, member_id: UUID) -> date | None:
        """End date of the member's latest membership (None = never subscribed)."""
        latest = self._latest_membership()
        stmt = select(latest.c.end_date).where(latest.c.member_id == member_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def has_subscriptions(self, member_id: UUID) -> bool:
        stmt = select(Subscription.id).where(Subscription.member_id == member_id,
                                             Subscription.is_delete.is_(False)).limit(1)
        return (await self._db.execute(stmt)).first() is not None
