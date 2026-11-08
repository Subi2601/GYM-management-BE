"""DB operations for membership actions (freeze, transfer, cancel / refund, documents). No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Integer, cast, func, select

from app.core.enums import MEMBERSHIP_PLAN_TYPES
from app.core.scope import BranchScope
from app.models.billing import Payment, Plan, Subscription
from app.models.member import Member
from app.models.membership import MemberDocument, Refund, SubscriptionFreeze
from app.repositories.base import BaseRepository


class MembershipRepository(BaseRepository):

    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    async def actionable_membership(self, member_id: UUID, scope: BranchScope,
                                    today: date) -> tuple[Subscription, Plan] | None:
        """The membership the desk acts on: the one running today, else the next one that hasn't started
        (not upgraded, not closed)."""
        stmt = (self.scoped(Subscription, select(Subscription, Plan).join(Plan, Plan.id == Subscription.plan_id),
                            scope)
                .where(Subscription.member_id == member_id, Plan.type.in_(MEMBERSHIP_PLAN_TYPES),
                       Subscription.upgraded_to_id.is_(None), Subscription.closed_reason.is_(None),
                       Subscription.end_date >= today)
                .order_by(Subscription.start_date.asc(), Subscription.created_at.asc()).limit(1))
        row = (await self._db.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def get_subscription(self, subscription_id: UUID, scope: BranchScope, *,
                               for_update: bool = False) -> tuple[Subscription, Plan] | None:
        stmt = (self.scoped(Subscription, select(Subscription, Plan).join(Plan, Plan.id == Subscription.plan_id),
                            scope).where(Subscription.id == subscription_id))
        if for_update:
            stmt = stmt.with_for_update(of=Subscription)
        row = (await self._db.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def later_memberships(self, member_id: UUID, after: date, exclude_id: UUID) -> list[Subscription]:
        """Membership rows of the member starting after `after` (queued renewals) — shifted when a freeze adds days."""
        stmt = (self.alive(Subscription, select(Subscription).join(Plan, Plan.id == Subscription.plan_id))
                .where(Subscription.member_id == member_id, Subscription.id != exclude_id,
                       Plan.type.in_(MEMBERSHIP_PLAN_TYPES), Subscription.start_date > after,
                       Subscription.closed_reason.is_(None), Subscription.upgraded_to_id.is_(None)))
        return list((await self._db.execute(stmt)).scalars().all())

    async def running_membership_for(self, member_id: UUID, today: date) -> Subscription | None:
        stmt = (self.alive(Subscription, select(Subscription).join(Plan, Plan.id == Subscription.plan_id))
                .where(Subscription.member_id == member_id, Plan.type.in_(MEMBERSHIP_PLAN_TYPES),
                       Subscription.closed_reason.is_(None), Subscription.upgraded_to_id.is_(None),
                       Subscription.end_date >= today).limit(1))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_payment(self, payment_id: UUID) -> Payment | None:
        return await self._db.get(Payment, payment_id)

    # ── freezes ──────────────────────────────────────────────────────────
    async def freezes(self, subscription_id: UUID) -> list[SubscriptionFreeze]:
        stmt = (self.alive(SubscriptionFreeze, select(SubscriptionFreeze))
                .where(SubscriptionFreeze.subscription_id == subscription_id)
                .order_by(SubscriptionFreeze.start_date.asc()))
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_freeze(self, freeze_id: UUID, scope: BranchScope) -> SubscriptionFreeze | None:
        return await self.get_scoped(SubscriptionFreeze, freeze_id, scope)

    async def frozen_on(self, member_id: UUID, day: date) -> SubscriptionFreeze | None:
        """The member's freeze covering `day` (check-in is refused while frozen)."""
        stmt = (self.alive(SubscriptionFreeze, select(SubscriptionFreeze))
                .where(SubscriptionFreeze.member_id == member_id, SubscriptionFreeze.start_date <= day,
                       SubscriptionFreeze.end_date >= day).limit(1))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    # ── documents ────────────────────────────────────────────────────────
    async def get_document(self, document_id: UUID, scope: BranchScope) -> MemberDocument | None:
        return await self.get_scoped(MemberDocument, document_id, scope)

    async def member_documents(self, member_id: UUID) -> list[MemberDocument]:
        """Without the file bytes (deferred), newest first."""
        from sqlalchemy.orm import defer
        stmt = (self.alive(MemberDocument, select(MemberDocument)).options(defer(MemberDocument.data))
                .where(MemberDocument.member_id == member_id).order_by(MemberDocument.created_at.desc()))
        return list((await self._db.execute(stmt)).scalars().all())

    async def document_names(self, ids: list[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        stmt = select(MemberDocument.id, MemberDocument.file_name).where(MemberDocument.id.in_(ids))
        return dict((await self._db.execute(stmt)).all())

    # ── refunds ──────────────────────────────────────────────────────────
    async def lock_refund_sequence(self, organization_id: UUID) -> None:
        await self._db.execute(select(func.pg_advisory_xact_lock(
            func.hashtext(func.concat("payment_refund:", str(organization_id))))))

    async def last_refund_number(self, organization_id: UUID) -> int:
        num = cast(func.substring(Refund.refund_no, 4), Integer)
        stmt = select(func.max(num)).where(Refund.organization_id == organization_id,
                                           Refund.refund_no.op("~")(r"^RF-\d+$"))
        return (await self._db.execute(stmt)).scalar_one() or 0

    async def refund_for(self, subscription_id: UUID) -> Refund | None:
        stmt = self.alive(Refund, select(Refund)).where(Refund.subscription_id == subscription_id).limit(1)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    def _refund_rows(self, scope: BranchScope):
        stmt = (select(Refund, Member.name, Member.registration_id, Member.phone, Plan.name)
                .join(Member, Member.id == Refund.member_id)
                .join(Subscription, Subscription.id == Refund.subscription_id)
                .join(Plan, Plan.id == Subscription.plan_id))
        return self.scoped(Refund, stmt, scope)

    async def list_refunds(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                           date_from: date | None, date_to: date | None) -> tuple[list, int]:
        stmt = self._refund_rows(scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(Member.name.ilike(pattern) | Member.phone.ilike(pattern)
                              | Member.registration_id.ilike(pattern) | Refund.refund_no.ilike(pattern))
        if date_from:
            stmt = stmt.where(Refund.refund_date >= date_from)
        if date_to:
            stmt = stmt.where(Refund.refund_date <= date_to)
        stmt = stmt.order_by(Refund.refund_date.desc(), Refund.created_at.desc(), Refund.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def get_refund_row(self, refund_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._refund_rows(scope).where(Refund.id == refund_id))).first()

    async def sum_refunds(self, scope: BranchScope, windows: dict[str, tuple[date | None, date | None]]) -> dict:
        cols = []
        for name, (start, end) in windows.items():
            conds = []
            if start is not None:
                conds.append(Refund.refund_date >= start)
            if end is not None:
                conds.append(Refund.refund_date <= end)
            expr = func.sum(Refund.amount)
            cols.append(func.coalesce(expr.filter(*conds) if conds else expr, 0).label(name))
        return dict((await self._db.execute(self.scoped(Refund, select(*cols), scope))).mappings().one())
