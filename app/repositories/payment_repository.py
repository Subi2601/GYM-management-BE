"""DB operations for payments, collection stats and invoice data. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import aliased

from app.core.enums import PaymentMode
from app.core.scope import BranchScope
from app.models.billing import Payment, Plan, Subscription
from app.models.member import Member
from app.models.organization import Branch, Organization
from app.models.training import PTSubscription
from app.repositories.base import BaseRepository


class PaymentRepository(BaseRepository):

    async def lock_receipt_sequence(self, organization_id: UUID) -> None:
        """Transaction-scoped advisory lock so concurrent payments of one organization get distinct receipts."""
        await self._db.execute(select(func.pg_advisory_xact_lock(
            func.hashtext(func.concat("payment_receipt:", str(organization_id))))))

    async def last_receipt_number(self, organization_id: UUID) -> int:
        """Highest numeric suffix of REC-#### receipts in the organization (deleted rows included)."""
        num = cast(func.substring(Payment.receipt_no, 5), Integer)
        stmt = select(func.max(num)).where(Payment.organization_id == organization_id,
                                           Payment.receipt_no.op("~")(r"^REC-\d+$"))
        return (await self._db.execute(stmt)).scalar_one() or 0

    async def get_payment(self, payment_id: UUID, scope: BranchScope) -> Payment | None:
        return await self.get_scoped(Payment, payment_id, scope)

    async def get_pt(self, pt_id: UUID, scope: BranchScope, *, for_update: bool = False) -> PTSubscription | None:
        stmt = self.scoped(PTSubscription, select(PTSubscription).where(PTSubscription.id == pt_id), scope)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_plan(self, plan_id: UUID) -> Plan | None:
        return (await self._db.execute(select(Plan).where(Plan.id == plan_id))).scalar_one_or_none()

    # ── list ─────────────────────────────────────────────────────────────
    def _list_stmt(self, scope: BranchScope):
        """Rows: (Payment, member_name, registration_id, member_phone, sub_plan_names[], pt_plan_name)."""
        names = (self.alive(Subscription, select(
                    Subscription.payment_id,
                    func.array_agg(aggregate_order_by(Plan.name, Subscription.created_at)).label("names"))
                 .join(Plan, Plan.id == Subscription.plan_id)
                 .where(Subscription.payment_id.is_not(None)))
                 .group_by(Subscription.payment_id).subquery())
        pt_plan = aliased(Plan)
        stmt = (select(Payment, Member.name, Member.registration_id, Member.phone, names.c.names, pt_plan.name)
                .join(Member, Member.id == Payment.member_id)
                .outerjoin(names, names.c.payment_id == Payment.id)
                .outerjoin(PTSubscription, PTSubscription.id == Payment.pt_subscription_id)
                .outerjoin(pt_plan, pt_plan.id == PTSubscription.plan_id))
        return self.scoped(Payment, stmt, scope)

    async def list_payments(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                            payment_mode: PaymentMode | None, date_from: date | None,
                            date_to: date | None, has_balance: bool | None = None,
                            sort_by: str | None = None, sort_dir: str = "desc") -> tuple[list, int]:
        stmt = self._list_stmt(scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Member.name.ilike(pattern), Member.registration_id.ilike(pattern),
                                  Member.phone.ilike(pattern), Payment.receipt_no.ilike(pattern)))
        if payment_mode:
            stmt = stmt.where(Payment.payment_mode == payment_mode)
        if date_from:
            stmt = stmt.where(Payment.payment_date >= date_from)
        if date_to:
            stmt = stmt.where(Payment.payment_date <= date_to)
        if has_balance is not None:
            stmt = stmt.where(Payment.balance_amount > 0 if has_balance else Payment.balance_amount == 0)
        columns = {"receipt_no": Payment.receipt_no, "payment_date": Payment.payment_date,
                   "member_name": Member.name, "paid_amount": Payment.paid_amount,
                   "balance_amount": Payment.balance_amount, "created_at": Payment.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir,
                            (Payment.payment_date.desc(), Payment.created_at.desc()), Payment.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def get_payment_row(self, payment_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._list_stmt(scope).where(Payment.id == payment_id))).first()

    # ── stats ────────────────────────────────────────────────────────────
    async def sum_paid(self, scope: BranchScope, windows: dict[str, tuple[date | None, date | None]],
                       cash_today: date) -> dict:
        """One scan: SUM(paid_amount) per named [from, to] window (None = open end), plus today's
        cash / non-cash split."""
        def _sum(*conds):
            expr = func.sum(Payment.paid_amount)
            if conds:
                expr = expr.filter(*conds)
            return func.coalesce(expr, 0)

        cols = []
        for name, (start, end) in windows.items():
            conds = []
            if start is not None:
                conds.append(Payment.payment_date >= start)
            if end is not None:
                conds.append(Payment.payment_date <= end)
            cols.append(_sum(*conds).label(name))
        is_today = Payment.payment_date == cash_today
        cols.append(_sum(is_today, Payment.payment_mode == PaymentMode.CASH).label("today_cash"))
        cols.append(_sum(is_today, Payment.payment_mode != PaymentMode.CASH).label("today_account"))
        row = (await self._db.execute(self.scoped(Payment, select(*cols), scope))).mappings().one()
        return dict(row)

    # ── invoice ──────────────────────────────────────────────────────────
    async def get_org_branch(self, organization_id: UUID, branch_id: UUID) -> tuple[Organization, Branch]:
        org = (await self._db.execute(select(Organization).where(Organization.id == organization_id))).scalar_one()
        branch = (await self._db.execute(select(Branch).where(Branch.id == branch_id))).scalar_one()
        return org, branch

    async def get_member(self, member_id: UUID) -> Member:
        return (await self._db.execute(select(Member).where(Member.id == member_id))).scalar_one()
