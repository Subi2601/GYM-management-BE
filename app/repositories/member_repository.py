"""DB operations for members. No business logic."""
from __future__ import annotations

import re
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, Integer, and_, cast, func, or_, select
from sqlalchemy.orm import aliased

from app.core.enums import MEMBERSHIP_PLAN_TYPES, Gender
from app.core.scope import BranchScope
from app.models.attendance import AttendanceSession
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.models.membership import SubscriptionFreeze
from app.repositories.base import BaseRepository

MEMBER_TABS = ("all", "active", "expiring", "absent", "inactive")


def _state_condition(latest, last_visit, state_filter: str | None, today: date, due_days: int,
                     absent_days: int) -> ColumnElement[bool] | None:
    """WHERE clause of a list tab on the latest membership; None = every member. Windows from Gym settings:
    `due_days` (expiring) and `absent_days` ("Not coming": running membership, no visit for that long — counted
    from the start for people who never came — and not frozen today)."""
    end = latest.c.end_date
    if state_filter == "active":
        return end >= today
    if state_filter == "inactive":
        return or_(end.is_(None), end < today)
    if state_filter == "expiring":
        return and_(end >= today, end <= today + timedelta(days=due_days))
    if state_filter == "absent":
        frozen = (select(SubscriptionFreeze.id)
                  .where(SubscriptionFreeze.member_id == Member.id, SubscriptionFreeze.is_delete.is_(False),
                         SubscriptionFreeze.start_date <= today, SubscriptionFreeze.end_date >= today).exists())
        return and_(end >= today, latest.c.start_date <= today - timedelta(days=absent_days),
                    func.coalesce(last_visit, latest.c.start_date) <= today - timedelta(days=absent_days),
                    ~frozen)
    return None


class MemberRepository(BaseRepository):

    def _latest_membership(self):
        """Latest MEMBERSHIP subscription per member (start_date desc, created_at desc)."""
        rn = func.row_number().over(partition_by=Subscription.member_id,
                                    order_by=(Subscription.start_date.desc(), Subscription.created_at.desc()))
        inner = (select(Subscription.member_id, Subscription.plan_id, Subscription.start_date,
                        Subscription.end_date, Plan.name.label("plan_name"), rn.label("rn"))
                 .join(Plan, Plan.id == Subscription.plan_id)
                 .where(Subscription.is_delete.is_(False), Plan.type.in_(MEMBERSHIP_PLAN_TYPES))
                 .subquery())
        return select(inner).where(inner.c.rn == 1).subquery()

    @staticmethod
    def _last_visits():
        """Each member's last check-in day (refused scans don't count)."""
        return (select(AttendanceSession.member_id, func.max(AttendanceSession.session_date).label("last_visit"))
                .where(AttendanceSession.member_id.is_not(None), AttendanceSession.denied_reason.is_(None),
                       AttendanceSession.is_delete.is_(False))
                .group_by(AttendanceSession.member_id).subquery())

    @staticmethod
    def _referral_counts():
        """How many (live) members each member referred."""
        return (select(Member.referred_by_id.label("referrer_id"), func.count(Member.id).label("referrals"))
                .where(Member.referred_by_id.is_not(None), Member.is_delete.is_(False))
                .group_by(Member.referred_by_id).subquery())

    def _list_stmt(self, scope: BranchScope):
        """Rows: (Member, plan_id, plan_name, end_date, last_visit, referred_by_name, referral_count)."""
        latest, visits, refs = self._latest_membership(), self._last_visits(), self._referral_counts()
        referrer = aliased(Member)
        stmt = (select(Member, latest.c.plan_id, latest.c.plan_name, latest.c.end_date, visits.c.last_visit,
                       referrer.name, func.coalesce(refs.c.referrals, 0))
                .outerjoin(latest, latest.c.member_id == Member.id)
                .outerjoin(visits, visits.c.member_id == Member.id)
                .outerjoin(referrer, referrer.id == Member.referred_by_id)
                .outerjoin(refs, refs.c.referrer_id == Member.id))
        return self.scoped(Member, stmt, scope), latest, visits.c.last_visit

    async def list_members(self, scope: BranchScope, *, offset: int, limit: int, today: date, due_days: int,
                           absent_days: int, search: str | None = None, state_filter: str | None = None,
                           plan_id: UUID | None = None, gender: Gender | None = None,
                           joined_from: date | None = None, joined_to: date | None = None,
                           sort_by: str | None = None, sort_dir: str = "desc") -> tuple[list, int]:
        """Rows: (Member, plan_id, plan_name, end_date, last_visit)."""
        stmt, latest, last_visit = self._list_stmt(scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Member.name.ilike(pattern), Member.phone.ilike(pattern),
                                  Member.registration_id.ilike(pattern)))
        end = latest.c.end_date
        state = _state_condition(latest, last_visit, state_filter, today, due_days, absent_days)
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
                   "joining_date": Member.joining_date, "expiry_date": end, "last_visit": last_visit,
                   "created_at": Member.created_at}
        # "Not coming": longest away first.
        default = ((last_visit.asc().nulls_first(),) if state_filter == "absent" else (Member.created_at.desc(),))
        stmt = self.ordered(stmt, columns, sort_by, sort_dir, default, Member.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope, today: date, due_days: int, absent_days: int) -> dict[str, int]:
        stmt, latest, last_visit = self._list_stmt(scope)
        return await self.count_tabs(stmt, {t: _state_condition(latest, last_visit, t, today, due_days, absent_days)
                                            for t in MEMBER_TABS})

    async def get_member_row(self, member_id: UUID, scope: BranchScope):
        stmt, _, _ = self._list_stmt(scope)
        return (await self._db.execute(stmt.where(Member.id == member_id))).first()

    async def referrer_chain(self, start_id: UUID, organization_id: UUID, limit: int = 50) -> list[UUID]:
        """[start, its referrer, theirs, …] inside the organization (empty = start isn't a live member)."""
        chain: list[UUID] = []
        current: UUID | None = start_id
        while current is not None and current not in chain and len(chain) < limit:
            row = (await self._db.execute(select(Member.id, Member.referred_by_id).where(
                Member.id == current, Member.organization_id == organization_id,
                Member.is_delete.is_(False)))).first()
            if row is None:
                break
            chain.append(row[0])
            current = row[1]
        return chain

    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    async def get_by_phone(self, branch_id: UUID, phone: str) -> Member | None:
        stmt = self.alive(Member, select(Member).where(Member.branch_id == branch_id, Member.phone == phone))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def last_registration_number(self, organization_id: UUID, prefix: str) -> int:
        """Highest numeric suffix of <prefix>-### registration ids in the organization (deleted rows included)."""
        num = cast(func.substring(Member.registration_id, len(prefix) + 2), Integer)
        stmt = select(func.max(num)).where(Member.organization_id == organization_id,
                                           Member.registration_id.op("~")(rf"^{re.escape(prefix)}-\d+$"))
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
