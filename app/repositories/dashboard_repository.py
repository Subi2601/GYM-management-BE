"""DB aggregates for the dashboard. No business logic."""
from __future__ import annotations

from datetime import date

from sqlalchemy import Date, cast, func, literal_column, select

from app.core.enums import MEMBERSHIP_PLAN_TYPES, LeadStatus
from app.core.scope import BranchScope
from app.models.billing import Payment, Plan, Subscription
from app.models.member import Lead, Member
from app.models.membership import Refund
from app.repositories.base import BaseRepository


# Inlined literal so SELECT and GROUP BY render the identical expression (bind params would differ).
_MONTH = literal_column("'month'")


class DashboardRepository(BaseRepository):

    def _latest_membership_end(self, scope: BranchScope):
        """Latest MEMBERSHIP subscription end date per member."""
        rn = func.row_number().over(partition_by=Subscription.member_id,
                                    order_by=(Subscription.start_date.desc(), Subscription.created_at.desc()))
        inner = self.scoped(Subscription, select(Subscription.member_id, Subscription.end_date, rn.label("rn"))
                            .join(Plan, Plan.id == Subscription.plan_id)
                            .where(Plan.type.in_(MEMBERSHIP_PLAN_TYPES)), scope).subquery()
        return select(inner.c.member_id, inner.c.end_date).where(inner.c.rn == 1).subquery()

    async def count_members(self, scope: BranchScope) -> int:
        stmt = self.scoped(Member, select(func.count(Member.id)), scope)
        return (await self._db.execute(stmt)).scalar_one()

    async def count_memberships_ending(self, scope: BranchScope, start: date, end: date | None) -> int:
        """Members whose latest membership ends on/after `start` (and on/before `end` when given)."""
        latest = self._latest_membership_end(scope)
        stmt = (select(func.count(Member.id)).join(latest, latest.c.member_id == Member.id)
                .where(latest.c.end_date >= start))
        if end is not None:
            stmt = stmt.where(latest.c.end_date <= end)
        return (await self._db.execute(self.scoped(Member, stmt, scope))).scalar_one()

    async def revenue(self, scope: BranchScope, today: date):
        """(total, today) collected minus refunds paid back."""
        stmt = select(func.coalesce(func.sum(Payment.paid_amount), 0),
                      func.coalesce(func.sum(Payment.paid_amount).filter(Payment.payment_date == today), 0))
        total, today_sum = (await self._db.execute(self.scoped(Payment, stmt, scope))).one()
        rstmt = select(func.coalesce(func.sum(Refund.amount), 0),
                       func.coalesce(func.sum(Refund.amount).filter(Refund.refund_date == today), 0))
        r_total, r_today = (await self._db.execute(self.scoped(Refund, rstmt, scope))).one()
        return total - r_total, today_sum - r_today

    async def count_open_leads(self, scope: BranchScope) -> int:
        stmt = self.scoped(Lead, select(func.count(Lead.id))
                           .where(Lead.status.in_((LeadStatus.NEW, LeadStatus.FOLLOW_UP))), scope)
        return (await self._db.execute(stmt)).scalar_one()

    async def new_members_by_month(self, scope: BranchScope, since: date) -> dict[date, int]:
        month = cast(func.date_trunc(_MONTH, Member.joining_date), Date)
        stmt = self.scoped(Member, select(month, func.count(Member.id))
                           .where(Member.joining_date >= since).group_by(month), scope)
        return {m: n for m, n in (await self._db.execute(stmt)).all()}

    async def revenue_by_month(self, scope: BranchScope, since: date) -> dict[date, object]:
        """Collected minus refunded, per month."""
        month = cast(func.date_trunc(_MONTH, Payment.payment_date), Date)
        stmt = self.scoped(Payment, select(month, func.sum(Payment.paid_amount))
                           .where(Payment.payment_date >= since).group_by(month), scope)
        out = {m: v for m, v in (await self._db.execute(stmt)).all()}
        r_month = cast(func.date_trunc(_MONTH, Refund.refund_date), Date)
        rstmt = self.scoped(Refund, select(r_month, func.sum(Refund.amount))
                            .where(Refund.refund_date >= since).group_by(r_month), scope)
        for m, v in (await self._db.execute(rstmt)).all():
            out[m] = (out.get(m) or 0) - v
        return out
