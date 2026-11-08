"""DB operations for the Renewals screen — each member's latest membership near or past its end. No business logic."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select

from app.core.enums import MEMBERSHIP_PLAN_TYPES
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.repositories.base import BaseRepository

RENEWAL_TABS = ("due", "overdue", "reminded", "all")


def _tab_condition(tab: str | None, today: date, within: int, overdue_days: int) -> ColumnElement[bool]:
    """`overdue_days` (Gym settings): lapsed memberships stay on the list this long; older ones are lost
    customers, not renewals."""
    due = and_(Subscription.end_date >= today, Subscription.end_date <= today + timedelta(days=within))
    overdue = and_(Subscription.end_date < today, Subscription.end_date >= today - timedelta(days=overdue_days))
    if tab == "due":
        return due
    if tab == "overdue":
        return overdue
    if tab == "reminded":
        return and_(or_(due, overdue), Subscription.reminded_at.is_not(None))
    return or_(due, overdue)


class RenewalRepository(BaseRepository):

    def _latest_membership_ids(self, scope: BranchScope):
        rn = func.row_number().over(partition_by=Subscription.member_id,
                                    order_by=(Subscription.start_date.desc(), Subscription.created_at.desc()))
        inner = self.scoped(Subscription, select(Subscription.id, rn.label("rn"))
                            .join(Plan, Plan.id == Subscription.plan_id)
                            .where(Plan.type.in_(MEMBERSHIP_PLAN_TYPES)), scope).subquery()
        return select(inner.c.id).where(inner.c.rn == 1)

    def _rows(self, scope: BranchScope):
        """(Subscription, member name, registration id, phone, plan name) — latest membership per member."""
        stmt = (select(Subscription, Member.name, Member.registration_id, Member.phone, Plan.name)
                .join(Member, Member.id == Subscription.member_id)
                .join(Plan, Plan.id == Subscription.plan_id)
                .where(Subscription.id.in_(self._latest_membership_ids(scope)), Member.is_delete.is_(False),
                       # cancelled / transferred away: not someone to remind
                       Subscription.closed_reason.is_(None)))
        return self.scoped(Subscription, stmt, scope)

    async def list_renewals(self, scope: BranchScope, *, offset: int, limit: int, today: date, within: int,
                            overdue_days: int, tab: str | None, search: str | None, sort_by: str | None,
                            sort_dir: str) -> tuple[list, int]:
        stmt = self._rows(scope).where(_tab_condition(tab, today, within, overdue_days))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Member.name.ilike(pattern), Member.phone.ilike(pattern),
                                  Member.registration_id.ilike(pattern)))
        columns = {"member_name": Member.name, "end_date": Subscription.end_date,
                   "reminded_at": Subscription.reminded_at}
        # Default: soonest / most recently lapsed first.
        stmt = self.ordered(stmt, columns, sort_by, sort_dir,
                            (func.abs(Subscription.end_date - today).asc(), Member.name.asc()), Subscription.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope, today: date, within: int, overdue_days: int) -> dict[str, int]:
        return await self.count_tabs(self._rows(scope),
                                     {t: _tab_condition(t, today, within, overdue_days) for t in RENEWAL_TABS})

    async def get_row(self, subscription_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._rows(scope).where(Subscription.id == subscription_id))).first()
