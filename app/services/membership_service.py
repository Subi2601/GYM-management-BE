"""Membership actions — freeze, transfer, cancel (with or without a refund). Manager level (`membership:manage`).

Rules (limits come from Gym settings and the plan):
- The desk acts on the membership running today (else the next one queued), never an upgraded / closed one.
- "Days used" = days from the start up to today, minus frozen days — so a member frozen for an emergency
  (pregnancy, accident) keeps their transfer / refund eligibility while frozen.
- Freeze: total days per membership = the member's own allowance, else the gym's freeze days (0 = only members
  given their own allowance); at most `freeze_max_times` freezes; one running at a time. The days are added to the
  end date at once (queued renewals move too); resuming early gives the unused days back.
- Transfer: once (a received membership can't move again), plain memberships only, fully paid, while days used
  ≤ the gym's transfer days. The receiver gets the remaining days from today; the giver's membership ends.
- Cancel: always possible; money back only on refundable plans, within the plan's refund days (or the gym's),
  up to what was paid — suggested amount = paid − the gym's deduction %.
Every action needs a reason; a proof document (PDF / photo) is optional.
"""
from __future__ import annotations

import base64
import binascii
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.encryption import decrypt_pii, encrypt_pii, mask_pii
from app.core.enums import DocumentKind, MembershipClose, PaymentMode, PlanType, SubscriptionStatus
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.models.membership import MemberDocument, Refund, SubscriptionFreeze
from app.repositories.member_repository import MemberRepository
from app.repositories.membership_repository import MembershipRepository
from app.schemas.member import MemberCreate
from app.schemas.membership import MAX_DOCUMENT_BYTES
from app.services.settings_service import GymSettings, SettingsService

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
# A freeze may start up to this many days back (the member stopped coming before the desk recorded it).
FREEZE_BACKDATE_DAYS = 30
_MODE = {PaymentMode.CASH: "cash", PaymentMode.UPI: "UPI", PaymentMode.CARD: "card",
         PaymentMode.BANK_TRANSFER: "bank transfer"}


def _dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _inr(v: Decimal) -> str:
    return f"₹{v:,.0f}" if v == v.to_integral() else f"₹{v:,.2f}"


def freeze_days(f: SubscriptionFreeze) -> int:
    return max(0, (f.end_date - f.start_date).days + 1)


def freeze_state(f: SubscriptionFreeze, today: date) -> str:
    if freeze_days(f) == 0 or f.end_date < today:
        return "DONE"
    return "UPCOMING" if f.start_date > today else "ACTIVE"


def used_days(sub: Subscription, freezes: list[SubscriptionFreeze], today: date) -> int:
    """Days of the membership already used: start → today (or its end), minus the frozen days in that span."""
    if today < sub.start_date:
        return 0
    upto = min(today, sub.end_date)
    total = (upto - sub.start_date).days + 1
    frozen = 0
    for f in freezes:
        lo, hi = max(f.start_date, sub.start_date), min(f.end_date, upto)
        if hi >= lo:
            frozen += (hi - lo).days + 1
    return max(0, total - frozen)


class MembershipService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = MembershipRepository(db)
        self._members = MemberRepository(db)
        self._settings = SettingsService(db)

    # ── helpers ──────────────────────────────────────────────────────────
    async def _member(self, member_id: UUID, scope: BranchScope) -> Member:
        member = await self._repo.get_member(member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        return member

    async def _subscription(self, subscription_id: UUID, scope: BranchScope) -> tuple[Subscription, Plan]:
        scope.require_branch()
        found = await self._repo.get_subscription(subscription_id, scope, for_update=True)
        if found is None:
            raise NotFoundError("Membership")
        sub, plan = found
        if sub.closed_reason:
            raise BadRequestError(f"This membership was already {sub.closed_reason.lower()} on {_dmy(sub.closed_on)}")
        if sub.upgraded_to_id:
            raise BadRequestError("This membership was upgraded. Act on the upgraded plan")
        if sub.end_date < timeutil.today():
            raise BadRequestError(f"{plan.name} already ended on {_dmy(sub.end_date)}")
        return sub, plan

    async def _document(self, upload, member: Member, sub: Subscription, kind: DocumentKind,
                        actor: RequestContext) -> MemberDocument | None:
        if upload is None:
            return None
        try:
            data = base64.b64decode(upload.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BadRequestError("The attached file couldn't be read. Attach it again") from exc
        if len(data) > MAX_DOCUMENT_BYTES:
            raise BadRequestError("The attached file is bigger than 5 MB. Attach a smaller photo or PDF")
        return await self._repo.add(MemberDocument(
            organization_id=member.organization_id, branch_id=member.branch_id, member_id=member.id,
            subscription_id=sub.id, kind=kind.value, file_name=upload.file_name.strip(),
            content_type=upload.content_type, size_bytes=len(data), data=data, created_by=actor.user_id))

    async def _shift_later(self, sub: Subscription, days: int, actor: RequestContext) -> None:
        """Queued renewals start after this membership: move them with its end."""
        for later in await self._repo.later_memberships(sub.member_id, sub.start_date, sub.id):
            later.start_date += timedelta(days=days)
            later.end_date += timedelta(days=days)
            later.updated_by = actor.user_id

    async def _stop_freezes(self, sub: Subscription, freezes: list[SubscriptionFreeze], today: date,
                            actor: RequestContext) -> None:
        """End a running freeze today / drop an upcoming one; the unused days come off the end date."""
        for f in freezes:
            state = freeze_state(f, today)
            if state == "DONE":
                continue
            before = freeze_days(f)
            f.end_date = today - timedelta(days=1)       # today the member is active again
            f.resumed_on = today
            unused = before - freeze_days(f)
            f.updated_by = actor.user_id
            sub.end_date -= timedelta(days=unused)
            sub.frozen_days = max(0, sub.frozen_days - unused)
            await self._shift_later(sub, -unused, actor)

    async def _paid_for(self, sub: Subscription, plan: Plan) -> Decimal:
        """What was actually paid for this membership (its share of the bill × the part of the bill paid, plus
        any upgrade credit already paid on the old plan)."""
        price = sub.price_share if sub.price_share is not None else plan.price
        credit = sub.upgrade_credit or ZERO
        own = price - sub.discount_amount - credit
        paid = ZERO
        if sub.payment_id and own > ZERO:
            payment = await self._repo.get_payment(sub.payment_id)
            if payment is not None:
                net = payment.amount - payment.discount_amount
                ratio = payment.paid_amount / net if net > ZERO else Decimal(1)
                paid = own * min(ratio, Decimal(1))
        return (credit + paid).quantize(CENT, rounding=ROUND_HALF_UP)

    # ── status ───────────────────────────────────────────────────────────
    @staticmethod
    def _freeze_out(f: SubscriptionFreeze, today: date, names: dict[UUID, str]) -> dict:
        return {"id": f.id, "start_date": f.start_date, "end_date": f.end_date, "days": freeze_days(f),
                "resumed_on": f.resumed_on, "reason": f.reason, "document_id": f.document_id,
                "document_name": names.get(f.document_id) if f.document_id else None,
                "state": freeze_state(f, today)}

    def _freeze_status(self, sub: Subscription, freezes: list[SubscriptionFreeze], s: GymSettings,
                       today: date, names: dict[UUID, str]) -> dict:
        counted = [f for f in freezes if freeze_days(f) > 0]
        allowance = sub.freeze_allowance_days if sub.freeze_allowance_days is not None else s.freeze_max_days
        remaining = max(0, allowance - sub.frozen_days)
        active = next((f for f in counted if freeze_state(f, today) != "DONE"), None)
        reason = None
        if not s.freeze_enabled:
            reason = "Freeze is switched off in Configuration"
        elif active is not None:
            reason = f"Already frozen {_dmy(active.start_date)} to {_dmy(active.end_date)}"
        elif allowance == 0:
            reason = "No freeze days for this member. Give them their own allowance to freeze"
        elif remaining == 0:
            reason = f"All {allowance} freeze days are used"
        elif len(counted) >= s.freeze_max_times:
            reason = f"Already frozen {len(counted)} time(s), the limit is {s.freeze_max_times}"
        return {"enabled": s.freeze_enabled, "allowed": reason is None, "reason": reason,
                "allowance_days": allowance, "custom_allowance": sub.freeze_allowance_days is not None,
                "gym_days": s.freeze_max_days, "used_days": sub.frozen_days, "remaining_days": remaining,
                "times_used": len(counted), "max_times": s.freeze_max_times,
                "active": self._freeze_out(active, today, names) if active else None}

    async def _transfer_status(self, sub: Subscription, plan: Plan, freezes, s: GymSettings, today: date) -> dict:
        used = used_days(sub, freezes, today)
        remaining = (sub.end_date - max(today, sub.start_date)).days + 1
        payment = await self._repo.get_payment(sub.payment_id) if sub.payment_id else None
        reason = None
        if not s.transfer_enabled:
            reason = "Transfer is switched off in Configuration"
        elif plan.type != PlanType.MEMBERSHIP:
            reason = "Only memberships can be transferred"
        elif sub.transferred_from_id is not None:
            reason = "This membership was received by transfer. A membership moves only once"
        elif plan.group_size > 1:
            reason = "Couple / family package memberships can't be transferred"
        elif payment is None:
            reason = "Collect the payment for this membership first"
        elif payment.balance_amount > ZERO:
            reason = f"Balance {_inr(payment.balance_amount)} is pending on {payment.receipt_no}. Collect it first"
        elif used > s.transfer_within_days:
            reason = (f"Used {used} days; transfers are allowed only within {s.transfer_within_days} days of use")
        return {"enabled": s.transfer_enabled, "allowed": reason is None, "reason": reason,
                "within_days": s.transfer_within_days, "used_days": used, "remaining_days": max(0, remaining)}

    async def _cancel_status(self, sub: Subscription, plan: Plan, freezes, s: GymSettings, today: date) -> dict:
        used = used_days(sub, freezes, today)
        window = plan.refund_window_days if plan.refund_window_days is not None else s.refund_within_days
        paid = await self._paid_for(sub, plan)
        pct = Decimal(s.refund_deduction_percent)
        deduction = (paid * pct / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
        reason = None
        if not plan.refundable:
            reason = f"{plan.name} isn't refundable (set on Plans & Pricing)"
        elif sub.transferred_from_id is not None:
            reason = "Received by transfer: no refund"
        elif paid <= ZERO:
            reason = "Nothing was paid for this membership"
        elif used > window:
            reason = f"Used {used} days; refunds are only within {window} days of use"
        return {"refund_eligible": reason is None, "refund_reason": reason, "refund_window_days": window,
                "used_days": used, "paid_amount": paid, "deduction_percent": pct,
                "deduction_amount": deduction if reason is None else ZERO,
                "suggested_refund": paid - deduction if reason is None else ZERO}

    async def actions(self, member_id: UUID, scope: BranchScope) -> dict:
        member = await self._member(member_id, scope)
        today = timeutil.today()
        found = await self._repo.actionable_membership(member.id, scope, today)
        if found is None:
            return {"current": None, "reason": "No running membership. Renew to add one", "freezes": []}
        sub, plan = found
        s = await self._settings.values(member.organization_id)
        freezes = await self._repo.freezes(sub.id)
        names = await self._repo.document_names([f.document_id for f in freezes if f.document_id])
        return {
            "current": {"subscription_id": sub.id, "plan_id": plan.id, "plan_name": plan.name,
                        "start_date": sub.start_date, "end_date": sub.end_date, "frozen_days": sub.frozen_days,
                        "received_by_transfer": sub.transferred_from_id is not None},
            "reason": None,
            "freezes": [self._freeze_out(f, today, names) for f in freezes if freeze_days(f) > 0],
            "freeze": self._freeze_status(sub, freezes, s, today, names),
            "transfer": await self._transfer_status(sub, plan, freezes, s, today),
            "cancel": await self._cancel_status(sub, plan, freezes, s, today),
        }

    # ── freeze ───────────────────────────────────────────────────────────
    async def set_allowance(self, subscription_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        sub, _ = await self._subscription(subscription_id, scope)
        if data.days is not None and data.days < sub.frozen_days:
            raise BadRequestError(f"{sub.frozen_days} days are already used; the allowance can't be lower")
        sub.freeze_allowance_days = data.days
        sub.updated_by = actor.user_id
        await self._repo.commit()
        return await self.actions(sub.member_id, scope)

    async def freeze(self, subscription_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        sub, plan = await self._subscription(subscription_id, scope)
        member = await self._member(sub.member_id, scope)
        today = timeutil.today()
        s = await self._settings.values(member.organization_id)
        freezes = await self._repo.freezes(sub.id)
        status = self._freeze_status(sub, freezes, s, today, {})
        if not status["allowed"]:
            raise BadRequestError(status["reason"])
        earliest = max(sub.start_date, today - timedelta(days=FREEZE_BACKDATE_DAYS))
        if data.start_date < earliest or data.start_date > sub.end_date:
            raise BadRequestError(f"Freeze start must be between {_dmy(earliest)} and {_dmy(sub.end_date)}")
        if data.days > status["remaining_days"]:
            raise BadRequestError(f"Only {status['remaining_days']} freeze day(s) left for this membership")
        doc = await self._document(data.document, member, sub, DocumentKind.FREEZE, actor)
        end = data.start_date + timedelta(days=data.days - 1)
        await self._repo.add(SubscriptionFreeze(
            organization_id=sub.organization_id, branch_id=sub.branch_id, subscription_id=sub.id,
            member_id=sub.member_id, start_date=data.start_date, end_date=end, reason=data.reason.strip(),
            document_id=doc.id if doc else None, created_by=actor.user_id))
        sub.end_date += timedelta(days=data.days)
        sub.frozen_days += data.days
        sub.updated_by = actor.user_id
        await self._shift_later(sub, data.days, actor)
        await self._repo.commit()
        return {"subscription_id": sub.id, "member_id": sub.member_id,
                "message": f"{member.name}'s {plan.name} frozen {_dmy(data.start_date)} to {_dmy(end)}. "
                           f"New end date {_dmy(sub.end_date)}"}

    async def resume(self, freeze_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        f = await self._repo.get_freeze(freeze_id, scope)
        if f is None:
            raise NotFoundError("Freeze")
        sub, plan = await self._subscription(f.subscription_id, scope)
        today = timeutil.today()
        if freeze_state(f, today) == "DONE":
            raise BadRequestError("This freeze is already over")
        await self._stop_freezes(sub, [f], today, actor)
        sub.updated_by = actor.user_id
        await self._repo.commit()
        member = await self._member(sub.member_id, scope)
        return {"subscription_id": sub.id, "member_id": sub.member_id,
                "message": f"{member.name}'s {plan.name} is active again. End date {_dmy(sub.end_date)}"}

    # ── transfer ─────────────────────────────────────────────────────────
    async def _receiver(self, data, giver: Member, scope: BranchScope, actor: RequestContext) -> Member:
        if data.to_member_id:
            person = await self._repo.get_member(data.to_member_id, scope)
            if person is None or person.branch_id != giver.branch_id:
                raise NotFoundError("Member")
        else:
            person = await self._members.get_by_phone(giver.branch_id, data.phone)
            if person is None:
                from app.services.member_service import MemberService     # avoids a service import cycle
                person = await MemberService(self._db)._build_member(
                    MemberCreate(name=data.name.strip(), phone=data.phone),
                    scope, giver.branch_id, actor)
        if person.id == giver.id:
            raise BadRequestError("Pick another person to transfer to")
        if await self._repo.running_membership_for(person.id, timeutil.today()) is not None:
            raise BadRequestError(f"{person.name} already has a running membership. Transfer to someone without one")
        return person

    async def transfer(self, subscription_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        sub, plan = await self._subscription(subscription_id, scope)
        giver = await self._member(sub.member_id, scope)
        today = timeutil.today()
        s = await self._settings.values(giver.organization_id)
        freezes = await self._repo.freezes(sub.id)
        status = await self._transfer_status(sub, plan, freezes, s, today)
        if not status["allowed"]:
            raise BadRequestError(status["reason"])
        receiver = await self._receiver(data, giver, scope, actor)
        await self._stop_freezes(sub, freezes, today, actor)
        start = max(today, sub.start_date)
        new = await self._repo.add(Subscription(
            organization_id=sub.organization_id, branch_id=sub.branch_id, member_id=receiver.id, plan_id=plan.id,
            payment_id=None, start_date=start, end_date=sub.end_date, price_share=ZERO, discount_amount=ZERO,
            status=SubscriptionStatus.ACTIVE, transferred_from_id=sub.id, created_by=actor.user_id))
        doc = await self._document(data.document, giver, sub, DocumentKind.TRANSFER, actor)
        sub.end_date = start - timedelta(days=1)
        sub.closed_reason, sub.closed_on = MembershipClose.TRANSFERRED.value, today
        sub.close_note = (f"Transferred to {receiver.name} ({receiver.registration_id}), "
                          f"{(new.end_date - new.start_date).days + 1} days left. Reason: {data.reason.strip()}"
                          + (f" · Proof: {doc.file_name}" if doc else ""))
        sub.transferred_to_id = new.id
        sub.updated_by = actor.user_id
        await self._repo.commit()
        return {"subscription_id": sub.id, "member_id": giver.id, "new_subscription_id": new.id,
                "new_member_id": receiver.id,
                "message": f"{plan.name} moved from {giver.name} to {receiver.name} till {_dmy(new.end_date)}"}

    # ── cancel / refund ──────────────────────────────────────────────────
    async def cancel(self, subscription_id: UUID, data, scope: BranchScope, actor: RequestContext,
                     show_pii: bool) -> dict:
        sub, plan = await self._subscription(subscription_id, scope)
        member = await self._member(sub.member_id, scope)
        today = timeutil.today()
        s = await self._settings.values(member.organization_id)
        freezes = await self._repo.freezes(sub.id)
        status = await self._cancel_status(sub, plan, freezes, s, today)
        refund = None
        if data.refund is not None:
            if not status["refund_eligible"]:
                raise BadRequestError(f"No refund: {status['refund_reason']}")
            amount = Decimal(str(data.refund.amount)).quantize(CENT, rounding=ROUND_HALF_UP)
            if amount > status["paid_amount"]:
                raise BadRequestError(f"Refund can't be more than what was paid ({_inr(status['paid_amount'])})")
            await self._repo.lock_refund_sequence(member.organization_id)
            r = data.refund
            refund = await self._repo.add(Refund(
                organization_id=sub.organization_id, branch_id=sub.branch_id,
                refund_no=f"RF-{await self._repo.last_refund_number(member.organization_id) + 1:04d}",
                member_id=member.id, subscription_id=sub.id, payment_id=sub.payment_id,
                paid_amount=status["paid_amount"], deduction_amount=status["paid_amount"] - amount, amount=amount,
                refund_date=today, refund_mode=r.mode, reason=data.reason.strip(),
                account_holder=(r.account_holder or "").strip() or None,
                bank_account_enc=encrypt_pii(r.account_number) if r.account_number else None,
                ifsc=r.ifsc, bank_name=(r.bank_name or "").strip() or None, upi_id=r.upi_id,
                reference=(r.reference or "").strip() or None, created_by=actor.user_id))
        doc = await self._document(data.document, member, sub, DocumentKind.CANCEL, actor)
        await self._stop_freezes(sub, freezes, today, actor)
        sub.end_date = max(today, sub.start_date) - timedelta(days=1)
        sub.closed_reason, sub.closed_on = MembershipClose.CANCELLED.value, today
        money_note = (f"Refund {_inr(refund.amount)} by {_MODE[refund.refund_mode]} ({refund.refund_no})"
                      if refund else "No refund")
        sub.close_note = (f"{money_note}. Reason: {data.reason.strip()}"
                          + (f" · Proof: {doc.file_name}" if doc else ""))
        sub.updated_by = actor.user_id
        await self._repo.commit()
        out = {"subscription_id": sub.id, "member_id": member.id,
               "message": f"{member.name}'s {plan.name} cancelled. {money_note}"}
        if refund is not None:
            out["refund"] = await self.get_refund(refund.id, scope, show_pii)
        return out

    # ── refunds list / documents ─────────────────────────────────────────
    @staticmethod
    def refund_out(r: Refund, name: str, registration_id: str, phone: str, plan_name: str, *,
                   show_pii: bool) -> dict:
        account = decrypt_pii(r.bank_account_enc)
        return {"id": r.id, "refund_no": r.refund_no, "member_id": r.member_id, "member_name": name,
                "registration_id": registration_id, "member_phone": phone, "plan_name": plan_name,
                "subscription_id": r.subscription_id, "paid_amount": r.paid_amount,
                "deduction_amount": r.deduction_amount, "amount": r.amount, "refund_date": r.refund_date,
                "refund_mode": r.refund_mode, "reason": r.reason, "account_holder": r.account_holder,
                "account_number": account if show_pii else mask_pii(account), "ifsc": r.ifsc,
                "bank_name": r.bank_name, "upi_id": r.upi_id, "reference": r.reference}

    async def get_refund(self, refund_id: UUID, scope: BranchScope, show_pii: bool) -> dict:
        row = await self._repo.get_refund_row(refund_id, scope)
        if row is None:
            raise NotFoundError("Refund")
        return self.refund_out(*row, show_pii=show_pii)

    async def list_refunds(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                           date_from: date | None, date_to: date | None, show_pii: bool) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_refunds(scope, offset=offset, limit=limit, search=search,
                                                    date_from=date_from, date_to=date_to)
        return [self.refund_out(*r, show_pii=show_pii) for r in rows], total

    async def document(self, document_id: UUID, scope: BranchScope) -> MemberDocument:
        doc = await self._repo.get_document(document_id, scope)
        if doc is None:
            raise NotFoundError("Document")
        return doc

    async def member_documents(self, member_id: UUID, scope: BranchScope) -> list[dict]:
        member = await self._member(member_id, scope)
        return [{"id": d.id, "subscription_id": d.subscription_id, "kind": d.kind, "file_name": d.file_name,
                 "content_type": d.content_type, "size_bytes": d.size_bytes, "created_at": d.created_at}
                for d in await self._repo.member_documents(member.id)]
