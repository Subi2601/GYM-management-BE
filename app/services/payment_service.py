"""Payments business logic — receipt numbers, server-side balance, paying subscriptions / PT, stats, invoice."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import share_token, timeutil
from app.core.enums import PaymentMode
from app.core.scope import BranchScope
from app.models.billing import Payment
from app.repositories.membership_repository import MembershipRepository
from app.services.gym_profile_service import GymProfileService
from app.repositories.payment_repository import PaymentRepository
from app.repositories.subscription_repository import SubscriptionRepository
from app.services.offer_service import OfferService

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: float | int | Decimal | None) -> Decimal:
    """Schema floats → exact 2-dp Decimal (via str, never binary float maths)."""
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def allocate(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split `total` across lines pro-rata to `weights`; the last line absorbs rounding."""
    base = sum(weights, ZERO)
    if total == ZERO or base == ZERO:
        parts = [ZERO] * len(weights)
        if weights:
            parts[-1] = total
        return parts
    parts = [(total * w / base).quantize(CENT, rounding=ROUND_DOWN) for w in weights]
    # Rounding goes to the last line that carries weight (a zero-weight line — e.g. outside an offer — stays 0).
    last = max(i for i, w in enumerate(weights) if w > ZERO)
    parts[last] += total - sum(parts, ZERO)
    return parts


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


class PaymentService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = PaymentRepository(db)
        self._subs = SubscriptionRepository(db)
        self._offers = OfferService(db)

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def payment_out(p: Payment, member_name: str, registration_id: str, member_phone: str,
                    sub_plan_names: list[str] | None, pt_plan_name: str | None) -> dict:
        if sub_plan_names:
            plan_names = list(sub_plan_names)
        elif p.pt_subscription_id:
            plan_names = [pt_plan_name or "Personal Training"]
        else:
            plan_names = []
        return {
            "id": p.id, "branch_id": p.branch_id, "receipt_no": p.receipt_no, "member_id": p.member_id,
            "member_name": member_name, "registration_id": registration_id, "member_phone": member_phone,
            "plan_names": plan_names, "pt_subscription_id": p.pt_subscription_id,
            "amount": p.amount, "discount_amount": p.discount_amount, "discount_reason": p.discount_reason,
            "paid_amount": p.paid_amount, "balance_amount": p.balance_amount,
            "balance_due_date": p.balance_due_date, "payment_date": p.payment_date,
            "payment_mode": p.payment_mode, "created_at": p.created_at, "updated_at": p.updated_at,
        }

    # ── shared builder (enrolment uses it too) — caller commits ─────────
    async def build_payment(self, *, scope: BranchScope, branch_id: UUID, member_id: UUID, gross: Decimal,
                            discount: Decimal, discount_reason: str | None, paid: Decimal, mode: PaymentMode,
                            balance_due_date: date | None, payment_date: date | None,
                            actor: RequestContext, pt_subscription_id: UUID | None = None) -> Payment:
        if discount > gross:
            raise BadRequestError(f"Discount ({discount}) cannot exceed the total amount ({gross})")
        net = gross - discount
        if paid > net:
            raise BadRequestError(f"Paid amount ({paid}) cannot exceed the payable amount ({net})")
        balance = net - paid
        await self._repo.lock_receipt_sequence(scope.organization_id)
        receipt_no = f"REC-{await self._repo.last_receipt_number(scope.organization_id) + 1:04d}"
        payment = Payment(
            organization_id=scope.organization_id, branch_id=branch_id, receipt_no=receipt_no,
            member_id=member_id, pt_subscription_id=pt_subscription_id,
            amount=gross, discount_amount=discount, discount_reason=discount_reason if discount else None,
            paid_amount=paid, balance_amount=balance,
            balance_due_date=balance_due_date if balance > ZERO else None,
            payment_date=payment_date or timeutil.today(), payment_mode=mode,
            created_by=actor.user_id,
        )
        return await self._repo.add(payment)

    # ── commands ─────────────────────────────────────────────────────────
    async def create_payment(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        if data.subscription_ids:
            payment = await self._pay_subscriptions(data, scope, branch_id, actor)
        else:
            payment = await self._pay_pt(data, scope, branch_id, actor)
        await self._repo.commit()
        return await self.get_payment(payment.id, scope)

    async def _pay_subscriptions(self, data, scope: BranchScope, branch_id: UUID, actor: RequestContext) -> Payment:
        subs = await self._subs.get_subscriptions(data.subscription_ids, scope, for_update=True)
        if len(subs) != len(data.subscription_ids) or any(s.branch_id != branch_id for s in subs):
            raise NotFoundError("Subscription")
        if len({s.member_id for s in subs}) != 1:
            raise BadRequestError("All subscriptions in one payment must belong to the same member")
        if any(s.payment_id is not None for s in subs):
            raise ConflictError("Subscription is already paid")
        subs.sort(key=lambda s: data.subscription_ids.index(s.id))
        plans = {p.id: p for p in await self._subs.get_plans([s.plan_id for s in subs], scope)}
        prices = [s.price_share if s.price_share is not None else plans[s.plan_id].price for s in subs]
        gross = sum(prices, ZERO)
        weights = prices
        applies = [False] * len(subs)
        if data.offer_id:
            discount, reason, applies = await self._offers.discount_for(
                data.offer_id, [(plans[s.plan_id].category_id, price) for s, price in zip(subs, prices)], scope)
            weights = [price if ok else ZERO for price, ok in zip(prices, applies)]
        elif data.discount_amount is None:            # use the discount captured on the subscriptions
            discount = sum((s.discount_amount for s in subs), ZERO)
            reason = data.discount_reason or next((s.discount_reason for s in subs if s.discount_reason), None)
        else:
            discount, reason = money(data.discount_amount), data.discount_reason
        payment = await self.build_payment(
            scope=scope, branch_id=branch_id, member_id=subs[0].member_id, gross=gross, discount=discount,
            discount_reason=reason, paid=money(data.paid_amount), mode=data.payment_mode,
            balance_due_date=data.balance_due_date, payment_date=data.payment_date, actor=actor)
        shares = allocate(discount, weights)
        for sub, share in zip(subs, shares):
            sub.payment_id = payment.id
            sub.discount_amount = share
            sub.discount_reason = reason if share else None
            sub.updated_by = actor.user_id
        for pt in await self._subs.get_pt_for_subscriptions([s.id for s in subs]):
            pt.is_paid = True
            pt.updated_by = actor.user_id
        payment.offer_bonus = await self._offers.apply_bonus(
            data.offer_id, [(s, plans[s.plan_id], ok) for s, ok in zip(subs, applies)], scope)
        return payment

    async def _pay_pt(self, data, scope: BranchScope, branch_id: UUID, actor: RequestContext) -> Payment:
        pt = await self._repo.get_pt(data.pt_subscription_id, scope, for_update=True)
        if pt is None or pt.branch_id != branch_id:
            raise NotFoundError("PT subscription")
        if pt.is_paid:
            raise ConflictError("PT subscription is already paid")
        if pt.subscription_id is not None:
            raise BadRequestError("This PT subscription is billed with its plan subscription — pay that "
                                  "subscription instead")
        plan = await self._repo.get_plan(pt.plan_id) if pt.plan_id else None
        if plan is None:
            raise BadRequestError("PT subscription has no plan to price it")
        discount, reason = money(data.discount_amount), data.discount_reason
        if data.offer_id:
            discount, reason, _ = await self._offers.discount_for(data.offer_id, [(plan.category_id, plan.price)],
                                                                  scope)
        payment = await self.build_payment(
            scope=scope, branch_id=branch_id, member_id=pt.member_id, gross=plan.price,
            discount=discount, discount_reason=reason,
            paid=money(data.paid_amount), mode=data.payment_mode, balance_due_date=data.balance_due_date,
            payment_date=data.payment_date, actor=actor, pt_subscription_id=pt.id)
        pt.is_paid = True
        pt.updated_by = actor.user_id
        return payment

    # ── queries ──────────────────────────────────────────────────────────
    async def list_payments(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                            payment_mode: PaymentMode | None, date_from: date | None,
                            date_to: date | None, has_balance: bool | None, sort_by: str | None,
                            sort_dir: str) -> tuple[list[dict], int]:
        if date_from and date_to and date_from > date_to:
            raise BadRequestError("date_from must be on or before date_to")
        rows, total = await self._repo.list_payments(scope, offset=offset, limit=limit, search=search,
                                                     payment_mode=payment_mode, date_from=date_from,
                                                     date_to=date_to, has_balance=has_balance,
                                                     sort_by=sort_by, sort_dir=sort_dir)
        return [self.payment_out(*r) for r in rows], total

    async def get_payment(self, payment_id: UUID, scope: BranchScope) -> dict:
        row = await self._repo.get_payment_row(payment_id, scope)
        if row is None:
            raise NotFoundError("Payment")
        return self.payment_out(*row)

    async def stats(self, scope: BranchScope) -> dict:
        today = timeutil.today()
        this_start, this_end = timeutil.month_bounds(today.year, today.month)
        last = this_start - timedelta(days=1)
        last_start, last_end = timeutil.month_bounds(last.year, last.month)
        windows = {
            "today": (today, today),
            "this_month": (this_start, this_end),
            "last_month": (last_start, last_end),
            "last_6_months": (add_months(today, -6), None),
            "last_12_months": (add_months(today, -12), None),
            "total": (None, None),
        }
        out = await self._repo.sum_paid(scope, windows, today)
        refunds = await MembershipRepository(self._repo._db).sum_refunds(
            scope, {k: windows[k] for k in ("today", "this_month", "last_month", "total")})
        out.update({f"refunds_{k}": v for k, v in refunds.items()})
        return out

    async def invoice(self, payment_id: UUID, scope: BranchScope) -> dict:
        payment = await self._repo.get_payment(payment_id, scope)
        if payment is None:
            raise NotFoundError("Payment")
        org, branch = await self._repo.get_org_branch(payment.organization_id, payment.branch_id)
        member = await self._repo.get_member(payment.member_id)
        lines: list[dict] = []
        credit, credit_label = ZERO, None
        if payment.pt_subscription_id:
            pt = await self._repo.get_pt(payment.pt_subscription_id, scope)
            plan = await self._repo.get_plan(pt.plan_id) if pt and pt.plan_id else None
            if pt is not None:
                lines.append({
                    "plan_name": plan.name if plan else "Personal Training",
                    "plan_type": plan.type if plan else None,
                    "service_type": plan.service_type if plan else None,
                    "duration_days": plan.duration_days if plan else None,
                    "total_sessions": pt.total_sessions, "start_date": pt.start_date,
                    "end_date": pt.expiry_date, "price": payment.amount,
                })
        else:
            for sub, plan in await self._subs.lines_for_payment(payment.id):
                if sub.upgrade_credit is not None and sub.upgraded_from_id:
                    credit = sub.upgrade_credit
                    old = await self._subs.get_row(sub.upgraded_from_id, scope)
                    old_payment = (await self._repo.get_payment(old[0].payment_id, scope)
                                   if old and old[0].payment_id else None)
                    credit_label = (f"Credit from {old[4].name if old else 'previous plan'}"
                                    + (f" ({old_payment.receipt_no})" if old_payment else ""))
                name = plan.name
                if sub.price_share is not None:          # group package: one line per member, their share
                    name = f"{plan.name} · {(await self._repo.get_member(sub.member_id)).name}"
                lines.append({
                    "plan_name": name, "plan_type": plan.type, "service_type": plan.service_type,
                    # Real days covered: calendar-month plans vary (3 months = 89-92 days).
                    "duration_days": ((sub.end_date - sub.start_date).days
                                      if sub.end_date and sub.start_date else plan.duration_days),
                    "total_sessions": plan.total_sessions,
                    "start_date": sub.start_date, "end_date": sub.end_date,
                    "price": sub.price_share if sub.price_share is not None else plan.price,
                })
        return {
            "payment_id": payment.id, "receipt_no": payment.receipt_no, "payment_date": payment.payment_date,
            "payment_mode": payment.payment_mode,
            "organization_name": org.name, "branch_name": branch.branch_name, "branch_location": branch.location,
            "member": {"id": member.id, "registration_id": member.registration_id, "name": member.name,
                       "phone": member.phone},
            "lines": lines,
            "credit_amount": credit, "credit_label": credit_label, "offer_bonus": payment.offer_bonus,
            "gym_code": org.code,
            # Letterhead (Gym Settings): the branch's own contacts / GSTIN when set, else the gym's.
            "tagline": org.tagline, "phone": branch.phone or org.contact_phone,
            "email": branch.email or org.contact_email, "gstin": branch.gstin or org.gstin,
            "invoice_footer": org.invoice_footer, **{k: v for k, v in (await GymProfileService(
                self._repo._db).links(org)).items() if k in ("logo_url", "terms_url")},
            "gross": payment.amount, "discount_amount": payment.discount_amount,
            "discount_reason": payment.discount_reason,
            "net_amount": payment.amount - payment.discount_amount,
            "paid_amount": payment.paid_amount, "balance_amount": payment.balance_amount,
            "balance_due_date": payment.balance_due_date,
            "share_token": share_token.sign("invoice", payment.id),
        }

    async def public_invoice(self, token: str) -> dict:
        """Invoice opened from a shared link (WhatsApp) — no login; the signed token is the permission."""
        payment_id = share_token.verify("invoice", token)
        payment = await self._repo.get_payment_unscoped(payment_id) if payment_id else None
        if payment is None:
            raise NotFoundError("Invoice")
        return await self.invoice(payment.id, BranchScope(payment.organization_id, payment.branch_id,
                                                          (payment.branch_id,)))
