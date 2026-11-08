"""DB operations for subscriptions (and the plan / member lookups they need). No business logic."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select

from app.core.enums import PlanType
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.models.training import PTSubscription
from app.repositories.base import BaseRepository

RENEWAL_WINDOW_DAYS = 3


def _renewal_condition(renewal_state: str | None, today: date) -> ColumnElement[bool] | None:
    """WHERE clause of a board tab on end_date; None = every row."""
    window = today + timedelta(days=RENEWAL_WINDOW_DAYS)
    if renewal_state == "EXPIRED":
        return Subscription.end_date < today
    if renewal_state == "EXPIRING":
        return and_(Subscription.end_date >= today, Subscription.end_date <= window)
    if renewal_state == "NONE":
        return Subscription.end_date > window
    return None


class SubscriptionRepository(BaseRepository):

    # ── lookups ──────────────────────────────────────────────────────────
    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    async def get_plans(self, plan_ids: list[UUID], scope: BranchScope) -> list[Plan]:
        stmt = self.scoped(Plan, select(Plan).where(Plan.id.in_(plan_ids)), scope)
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_subscriptions(self, ids: list[UUID], scope: BranchScope, *,
                                for_update: bool = False) -> list[Subscription]:
        stmt = self.scoped(Subscription, select(Subscription).where(Subscription.id.in_(ids)), scope)
        if for_update:
            stmt = stmt.with_for_update()
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_pt_for_subscriptions(self, subscription_ids: list[UUID]) -> list[PTSubscription]:
        stmt = self.alive(PTSubscription, select(PTSubscription)
                          .where(PTSubscription.subscription_id.in_(subscription_ids)))
        return list((await self._db.execute(stmt)).scalars().all())

    # ── joined reads ─────────────────────────────────────────────────────
    @staticmethod
    def _row_select():
        """Rows: (Subscription, member_name, registration_id, member_phone, Plan)."""
        return (select(Subscription, Member.name, Member.registration_id, Member.phone, Plan)
                .join(Member, Member.id == Subscription.member_id)
                .join(Plan, Plan.id == Subscription.plan_id))

    def _latest_ids(self, scope: BranchScope):
        rn = func.row_number().over(partition_by=Subscription.member_id,
                                    order_by=(Subscription.start_date.desc(), Subscription.created_at.desc()))
        inner = self.scoped(Subscription, select(Subscription.id, rn.label("rn")), scope).subquery()
        return select(inner.c.id).where(inner.c.rn == 1)

    def _board_stmt(self, scope: BranchScope):
        """Latest subscription per (non-deleted) member."""
        return self.scoped(Subscription, self._row_select(), scope).where(
            Subscription.id.in_(self._latest_ids(scope)), Member.is_delete.is_(False))

    async def list_board(self, scope: BranchScope, *, offset: int, limit: int, today: date,
                         search: str | None, renewal_state: str | None, plan_id: UUID | None = None,
                         sort_by: str | None = None, sort_dir: str = "desc") -> tuple[list, int]:
        stmt = self._board_stmt(scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Member.name.ilike(pattern), Member.phone.ilike(pattern),
                                  Member.registration_id.ilike(pattern), Plan.name.ilike(pattern)))
        renewal = _renewal_condition(renewal_state, today)
        if renewal is not None:
            stmt = stmt.where(renewal)
        if plan_id:
            stmt = stmt.where(Subscription.plan_id == plan_id)
        columns = {"member_name": Member.name, "plan_name": Plan.name, "start_date": Subscription.start_date,
                   "end_date": Subscription.end_date, "created_at": Subscription.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir,
                            (Subscription.start_date.desc(), Subscription.created_at.desc()), Subscription.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def board_counts(self, scope: BranchScope, today: date) -> dict[str, int]:
        tabs = {"all": None, "expiring": "EXPIRING", "expired": "EXPIRED", "active": "NONE"}
        return await self.count_tabs(self._board_stmt(scope),
                                     {key: _renewal_condition(state, today) for key, state in tabs.items()})

    async def list_for_member(self, member_id: UUID, scope: BranchScope) -> list:
        stmt = (self.scoped(Subscription, self._row_select(), scope)
                .where(Subscription.member_id == member_id)
                .order_by(Subscription.start_date.desc(), Subscription.created_at.desc()))
        return list((await self._db.execute(stmt)).all())

    async def get_row(self, subscription_id: UUID, scope: BranchScope):
        stmt = self.scoped(Subscription, self._row_select(), scope).where(Subscription.id == subscription_id)
        return (await self._db.execute(stmt)).first()

    async def lines_for_payment(self, payment_id: UUID) -> list[tuple[Subscription, Plan]]:
        stmt = (self.alive(Subscription, select(Subscription, Plan)
                           .join(Plan, Plan.id == Subscription.plan_id)
                           .where(Subscription.payment_id == payment_id))
                .order_by(Subscription.created_at, Plan.name))
        return [tuple(r) for r in (await self._db.execute(stmt)).all()]

    async def current_membership(self, member_id: UUID, scope: BranchScope) -> tuple[Subscription, Plan] | None:
        """The member's latest membership-type subscription that hasn't been upgraded (same order as the board)."""
        stmt = (self.scoped(Subscription, select(Subscription, Plan).join(Plan, Plan.id == Subscription.plan_id),
                            scope)
                .where(Subscription.member_id == member_id, Plan.type == PlanType.MEMBERSHIP,
                       Subscription.upgraded_to_id.is_(None), Subscription.closed_reason.is_(None))
                .order_by(Subscription.start_date.desc(), Subscription.created_at.desc()).limit(1))
        row = (await self._db.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def pt_id_for_subscription(self, subscription_id: UUID) -> UUID | None:
        stmt = self.alive(PTSubscription, select(PTSubscription.id)
                          .where(PTSubscription.subscription_id == subscription_id)).limit(1)
        return (await self._db.execute(stmt)).scalar_one_or_none()
