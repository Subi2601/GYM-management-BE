"""Subscriptions business logic — renewal board, history, atomic multi-plan enrolment, unpaid subscriptions."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import PaymentStatus, PlanServiceType, PlanType, PTStatus, RenewalState, SubscriptionStatus
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.models.staff import Employee
from app.models.training import PTSubscription
from app.repositories.membership_repository import MembershipRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.plan_repository import PlanRepository
from app.repositories.subscription_repository import RENEWAL_WINDOW_DAYS, SubscriptionRepository
from app.repositories.training_repository import TrainingRepository
from app.services.offer_service import OfferService
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberCreate
from app.services.payment_service import ZERO, PaymentService, add_months, allocate, money


def plan_end(plan: Plan, start: date) -> date:
    """Calendar months when the plan is sold in months (5 Nov + 3 → 5 Feb), otherwise start + days."""
    if plan.duration_months:
        return add_months(start, plan.duration_months)
    return start + timedelta(days=plan.duration_days)


def renewal_state(end_date: date, today: date) -> RenewalState:
    if end_date < today:
        return RenewalState.EXPIRED
    if end_date <= today + timedelta(days=RENEWAL_WINDOW_DAYS):
        return RenewalState.EXPIRING
    return RenewalState.NONE


class SubscriptionService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = SubscriptionRepository(db)
        self._payments_repo = PaymentRepository(db)
        self._training = TrainingRepository(db)
        self._payments = PaymentService(db)
        self._offers = OfferService(db)
        self._members = MemberRepository(db)
        self._plans = PlanRepository(db)
        self._db = db

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def subscription_out(s: Subscription, member_name: str, registration_id: str, member_phone: str,
                         plan: Plan, *, today: date) -> dict:
        return {
            "id": s.id, "branch_id": s.branch_id, "member_id": s.member_id, "member_name": member_name,
            "registration_id": registration_id, "member_phone": member_phone,
            "plan_id": plan.id, "plan_name": plan.name, "plan_type": plan.type, "service_type": plan.service_type,
            "price": s.price_share if s.price_share is not None else plan.price,
            "start_date": s.start_date, "end_date": s.end_date,
            "discount_amount": s.discount_amount, "discount_reason": s.discount_reason, "status": s.status,
            # A membership received by transfer was paid by the giver.
            "payment_id": s.payment_id,
            "payment_status": PaymentStatus.PAID if s.payment_id or s.transferred_from_id else PaymentStatus.PENDING,
            "renewal_state": renewal_state(s.end_date, today), "days_left": (s.end_date - today).days,
            "upgraded_to_id": s.upgraded_to_id, "upgraded_from_id": s.upgraded_from_id,
            "upgrade_credit": s.upgrade_credit,
            "frozen_days": s.frozen_days, "closed_reason": s.closed_reason, "closed_on": s.closed_on,
            "close_note": s.close_note, "transferred_to_id": s.transferred_to_id,
            "transferred_from_id": s.transferred_from_id,
            "created_at": s.created_at, "updated_at": s.updated_at,
        }

    @staticmethod
    def _line(s: Subscription, plan: Plan) -> dict:
        return {"subscription_id": s.id, "plan_id": plan.id, "plan_name": plan.name, "plan_type": plan.type,
                "service_type": plan.service_type, "duration_days": plan.duration_days,
                "total_sessions": plan.total_sessions, "start_date": s.start_date, "end_date": s.end_date,
                "price": s.price_share if s.price_share is not None else plan.price}

    # ── queries ──────────────────────────────────────────────────────────
    async def list_board(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                         renewal_state_filter: str | None, plan_id: UUID | None, sort_by: str | None,
                         sort_dir: str) -> tuple[list[dict], int]:
        today = timeutil.today()
        rows, total = await self._repo.list_board(scope, offset=offset, limit=limit, today=today,
                                                  search=search, renewal_state=renewal_state_filter,
                                                  plan_id=plan_id, sort_by=sort_by, sort_dir=sort_dir)
        return [self.subscription_out(*r, today=today) for r in rows], total

    async def board_counts(self, scope: BranchScope) -> dict:
        return await self._repo.board_counts(scope, timeutil.today())

    async def list_for_member(self, member_id: UUID, scope: BranchScope) -> list[dict]:
        if await self._repo.get_member(member_id, scope) is None:
            raise NotFoundError("Member")
        today = timeutil.today()
        return [self.subscription_out(*r, today=today) for r in await self._repo.list_for_member(member_id, scope)]

    async def get_detail(self, subscription_id: UUID, scope: BranchScope) -> dict:
        row = await self._repo.get_row(subscription_id, scope)
        if row is None:
            raise NotFoundError("Subscription")
        sub, member_name, registration_id, member_phone, plan = row
        out = self.subscription_out(*row, today=timeutil.today())
        out["member"] = {"id": sub.member_id, "registration_id": registration_id, "name": member_name,
                         "phone": member_phone}
        payment = None
        if sub.payment_id:
            payment = await self._payments_repo.get_payment(sub.payment_id, scope)
            lines = await self._repo.lines_for_payment(sub.payment_id)
        else:
            lines = [(sub, plan)]
        out["plans"] = [self._line(s, p) for s, p in lines]
        out["payment"] = None if payment is None else {
            "id": payment.id, "receipt_no": payment.receipt_no, "payment_date": payment.payment_date,
            "payment_mode": payment.payment_mode, "amount": payment.amount,
            "discount_amount": payment.discount_amount, "paid_amount": payment.paid_amount,
            "balance_amount": payment.balance_amount, "balance_due_date": payment.balance_due_date,
        }
        out["pt_subscription_id"] = await self._repo.pt_id_for_subscription(sub.id)
        return out

    # ── shared validation ────────────────────────────────────────────────
    async def _member_in_branch(self, member_id: UUID, scope: BranchScope, branch_id: UUID) -> Member:
        member = await self._repo.get_member(member_id, scope)
        if member is None or member.branch_id != branch_id:
            raise NotFoundError("Member")
        return member

    async def _plans_in_branch(self, plan_ids: list[UUID], scope: BranchScope, branch_id: UUID) -> list[Plan]:
        found = {p.id: p for p in await self._repo.get_plans(plan_ids, scope) if p.branch_id == branch_id}
        if len(found) != len(plan_ids):
            raise NotFoundError("Plan")
        return [found[pid] for pid in plan_ids]

    async def _group_members(self, plans: list[Plan], wanted, payer: Member, scope: BranchScope, branch_id: UUID,
                             actor: RequestContext) -> list[Member]:
        """The other members of a group package (existing ones, or new ones created now). Caller commits."""
        group_plans = [p for p in plans if p.group_size > 1]
        if len(group_plans) > 1:
            raise BadRequestError("Bill one group package at a time")
        if not group_plans:
            if wanted:
                raise BadRequestError("Only a group package (couple, family …) takes other members")
            return []
        plan = group_plans[0]
        needed = plan.group_size - 1
        if len(wanted) != needed:
            raise BadRequestError(f"{plan.name} covers {plan.group_size} members: add {needed} besides "
                                  f"{payer.name} (you added {len(wanted)})")
        people: list[Member] = []
        for w in wanted:
            if w.member_id:
                person = await self._member_in_branch(w.member_id, scope, branch_id)
            else:
                # Someone already registered with that phone is used as is — no duplicate member.
                person = await self._members.get_by_phone(branch_id, w.phone)
                if person is None:
                    from app.services.member_service import MemberService   # avoids a service import cycle
                    person = await MemberService(self._db)._build_member(
                        MemberCreate(name=w.name, phone=w.phone), scope, branch_id, actor)
            if person.id == payer.id or any(p.id == person.id for p in people):
                raise BadRequestError(f"{person.name} is already in this package")
            people.append(person)
        return people

    async def _trainer(self, trainer_id: UUID | None, branch_id: UUID) -> Employee | None:
        if trainer_id is None:
            return None
        trainer = await self._training.get_active_trainer(trainer_id, branch_id)
        if trainer is None:
            raise NotFoundError("Trainer")
        return trainer

    async def _add_subscription(self, *, scope: BranchScope, branch_id: UUID, member: Member, plan: Plan,
                                start: date, discount, discount_reason: str | None, payment_id: UUID | None,
                                trainer: Employee | None, actor: RequestContext,
                                price_share=None) -> tuple[Subscription, UUID | None]:
        """One subscription (+ PT record for PERSONAL_TRAINING plans). Caller commits."""
        sub = await self._repo.add(Subscription(
            organization_id=scope.organization_id, branch_id=branch_id, member_id=member.id, plan_id=plan.id,
            payment_id=payment_id, start_date=start, end_date=plan_end(plan, start), price_share=price_share,
            discount_amount=discount, discount_reason=discount_reason if discount else None,
            status=SubscriptionStatus.ACTIVE, created_by=actor.user_id,
        ))
        pt_id = None
        if plan.service_type == PlanServiceType.PERSONAL_TRAINING:
            pt = await self._repo.add(PTSubscription(
                organization_id=scope.organization_id, branch_id=branch_id, member_id=member.id,
                trainer_id=trainer.id if trainer else None, plan_id=plan.id, subscription_id=sub.id,
                goal=member.fitness_goal, total_sessions=plan.total_sessions,
                sessions_remaining=plan.total_sessions, start_date=start, expiry_date=sub.end_date,
                is_paid=payment_id is not None, status=PTStatus.ACTIVE, created_by=actor.user_id,
            ))
            pt_id = pt.id
        return sub, pt_id

    # ── commands ─────────────────────────────────────────────────────────
    async def enroll(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        """Subscriptions + payment + PT records in one transaction — all or nothing."""
        branch_id = scope.require_branch()
        member = await self._member_in_branch(data.member_id, scope, branch_id)
        plans = await self._plans_in_branch(data.plan_ids, scope, branch_id)
        inactive = [p.name for p in plans if not p.is_active]
        if inactive:
            raise BadRequestError(f"{', '.join(inactive)} is inactive. Activate it on Plans & Pricing to sell it")
        checks = [p.id_check for p in plans if p.id_check]
        if checks and not data.id_verified:
            raise BadRequestError(f"Confirm the {checks[0]} is verified to continue")
        group = await self._group_members(plans, data.group_members, member, scope, branch_id, actor)
        trainer = await self._trainer(data.trainer_id, branch_id)
        start = data.start_date or timeutil.today()

        # One billing line per membership: a group plan is split evenly across its members.
        lines: list[tuple[Plan, Member, object]] = []        # (plan, member, price_share or None)
        for plan in plans:
            if plan.group_size > 1:
                people = [member, *group]
                for person, share in zip(people, allocate(plan.price, [Decimal(1)] * len(people))):
                    lines.append((plan, person, share))
            else:
                lines.append((plan, member, None))
        prices = [share if share is not None else plan.price for plan, _, share in lines]
        gross = sum(prices, ZERO)

        pay = data.payment
        discount, reason, weights = money(pay.discount_amount), pay.discount_reason, prices
        applies = [False] * len(lines)
        if pay.offer_id:
            discount, reason, applies = await self._offers.discount_for(
                pay.offer_id, [(plan.category_id, price) for (plan, _, _), price in zip(lines, prices)], scope)
            weights = [price if ok else ZERO for price, ok in zip(prices, applies)]
        payment = await self._payments.build_payment(
            scope=scope, branch_id=branch_id, member_id=member.id, gross=gross, discount=discount,
            discount_reason=reason, paid=money(pay.paid_amount), mode=pay.payment_mode,
            balance_due_date=pay.balance_due_date, payment_date=pay.payment_date, actor=actor)
        sub_ids, pt_ids, billed = [], [], []
        for (plan, person, share), disc, ok in zip(lines, allocate(discount, weights), applies):
            sub, pt_id = await self._add_subscription(
                scope=scope, branch_id=branch_id, member=person, plan=plan, start=start, discount=disc,
                discount_reason=reason, payment_id=payment.id, trainer=trainer, actor=actor, price_share=share)
            sub_ids.append(sub.id)
            billed.append((sub, plan, ok))
            if pt_id:
                pt_ids.append(pt_id)
        payment.offer_bonus = await self._offers.apply_bonus(pay.offer_id, billed, scope)
        await self._repo.commit()
        return {"payment_id": payment.id, "receipt_no": payment.receipt_no, "subscription_ids": sub_ids,
                "pt_subscription_ids": pt_ids, "amount": payment.amount,
                "discount_amount": payment.discount_amount, "paid_amount": payment.paid_amount,
                "balance_amount": payment.balance_amount}

    async def create_subscription(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        """Single unpaid subscription (paid later via POST /payments)."""
        branch_id = scope.require_branch()
        member = await self._member_in_branch(data.member_id, scope, branch_id)
        (plan,) = await self._plans_in_branch([data.plan_id], scope, branch_id)
        trainer = await self._trainer(data.trainer_id, branch_id)
        discount = money(data.discount_amount)
        if discount > plan.price:
            raise BadRequestError(f"Discount ({discount}) cannot exceed the plan price ({plan.price})")
        sub, _ = await self._add_subscription(
            scope=scope, branch_id=branch_id, member=member, plan=plan,
            start=data.start_date or timeutil.today(), discount=discount, discount_reason=data.discount_reason,
            payment_id=None, trainer=trainer, actor=actor)
        await self._repo.commit()
        return await self.get_detail(sub.id, scope)

    # ── upgrade ──────────────────────────────────────────────────────────
    async def _upgrade_context(self, member: Member, scope: BranchScope) -> dict:
        """The member's current membership, its credit and upgrade window, and why an upgrade isn't possible."""
        today = timeutil.today()
        found = await self._repo.current_membership(member.id, scope)
        if found is None:
            return {"sub": None, "plan": None, "problem": "No membership to upgrade. Use Renew to add one"}
        sub, plan = found
        price = sub.price_share if sub.price_share is not None else plan.price
        credit = price - sub.discount_amount
        window_ends = sub.start_date + timedelta(days=plan.upgrade_window_days) if plan.upgrade_window_days else None
        payment = await self._payments_repo.get_payment(sub.payment_id, scope) if sub.payment_id else None
        problem = None
        frozen = await MembershipRepository(self._db).frozen_on(member.id, today)
        if plan.group_size > 1:
            problem = "Couple / family packages can't be upgraded yet. Use Renew"
        elif sub.transferred_from_id is not None:
            problem = "This membership was received by transfer, so it can't be upgraded. Use Renew"
        elif frozen is not None and frozen.subscription_id == sub.id:
            problem = f"The membership is frozen till {frozen.end_date:%d-%m-%Y}. Resume it first"
        elif sub.end_date < today:
            problem = f"{plan.name} ended on {sub.end_date:%d-%m-%Y}. Use Renew"
        elif window_ends is None:
            problem = f"Upgrades are off for {plan.name}. Use Renew"
        elif today > window_ends:
            problem = (f"Upgrade window closed on {window_ends:%d-%m-%Y} ({plan.upgrade_window_days} days from the "
                       f"start). Use Renew")
        elif payment is None:
            problem = "Collect the payment for the current plan first"
        elif payment.balance_amount > ZERO:
            problem = f"Balance ₹{payment.balance_amount:,} is pending on {payment.receipt_no}. Collect it first"
        return {"sub": sub, "plan": plan, "credit": credit, "window_ends": window_ends, "problem": problem,
                "receipt_no": payment.receipt_no if payment else None}

    @staticmethod
    def _option_reason(target: Plan, current: Plan) -> str | None:
        """Why `target` isn't an upgrade of `current` (None = it is): higher price and at least as long."""
        if target.id == current.id:
            return "Current plan"
        if target.group_size > 1:
            return "Couple / family package: use Renew"
        if target.price < current.price:
            return "Lower price than current plan"
        if target.price == current.price:
            return "Same price as current plan"
        if target.duration_days < current.duration_days:
            return "Shorter than current plan"
        return None

    async def upgrade_options(self, member_id: UUID, scope: BranchScope) -> dict:
        member = await self._repo.get_member(member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        ctx = await self._upgrade_context(member, scope)
        sub, current = ctx["sub"], ctx["plan"]
        rows, _ = await self._plans.list_plans(scope, offset=0, limit=500, plan_type=PlanType.MEMBERSHIP,
                                               active_only=True)
        options = []
        for plan, category_name in rows:
            if plan.branch_id != member.branch_id:
                continue
            reason = self._option_reason(plan, current) if current else "No current plan"
            options.append({
                "plan_id": plan.id, "name": plan.name, "category_id": plan.category_id,
                "category_name": category_name, "duration_months": plan.duration_months,
                "duration_days": plan.duration_days, "price": plan.price, "id_check": plan.id_check,
                "eligible": reason is None and ctx["problem"] is None, "reason": reason,
                "balance": max(plan.price - ctx["credit"], ZERO) if current else plan.price,
            })
        out_current = None
        if sub is not None:
            out_current = {
                "subscription_id": sub.id, "plan_id": current.id, "plan_name": current.name,
                "category_name": next((o["category_name"] for o in options if o["plan_id"] == current.id), ""),
                "start_date": sub.start_date, "end_date": sub.end_date, "credit": ctx["credit"],
                "receipt_no": ctx["receipt_no"], "window_days": current.upgrade_window_days,
                "window_ends": ctx["window_ends"],
            }
        return {"current": out_current, "can_upgrade": ctx["problem"] is None, "reason": ctx["problem"],
                "options": options}

    async def upgrade(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        """Bigger plan from the old start date; the old plan's cost is credited and only the balance billed."""
        branch_id = scope.require_branch()
        member = await self._member_in_branch(data.member_id, scope, branch_id)
        ctx = await self._upgrade_context(member, scope)
        if ctx["problem"]:
            raise BadRequestError(ctx["problem"])
        (old,) = await self._repo.get_subscriptions([ctx["sub"].id], scope, for_update=True)
        if old.upgraded_to_id is not None:
            raise BadRequestError("This plan was just upgraded. Refresh and try again")
        current: Plan = ctx["plan"]
        (target,) = await self._plans_in_branch([data.plan_id], scope, branch_id)
        if not target.is_active or target.type != PlanType.MEMBERSHIP:
            raise BadRequestError(f"{target.name} can't be sold right now")
        reason = self._option_reason(target, current)
        if reason:
            raise BadRequestError(f"{target.name}: {reason}. Pick a bigger plan")
        if target.id_check and not data.id_verified:
            raise BadRequestError(f"Confirm the {target.id_check} is verified to continue")

        credit: Decimal = ctx["credit"]
        balance = target.price - credit
        pay = data.payment
        discount, discount_reason, applies = money(pay.discount_amount), pay.discount_reason, [False]
        if pay.offer_id:
            discount, discount_reason, applies = await self._offers.discount_for(
                pay.offer_id, [(target.category_id, balance)], scope)
        payment = await self._payments.build_payment(
            scope=scope, branch_id=branch_id, member_id=member.id, gross=balance, discount=discount,
            discount_reason=discount_reason, paid=money(pay.paid_amount), mode=pay.payment_mode,
            balance_due_date=pay.balance_due_date, payment_date=pay.payment_date, actor=actor)
        new, _ = await self._add_subscription(
            scope=scope, branch_id=branch_id, member=member, plan=target, start=old.start_date, discount=discount,
            discount_reason=discount_reason, payment_id=payment.id, trainer=None, actor=actor)
        new.upgraded_from_id, new.upgrade_credit = old.id, credit
        # Days the old plan was frozen stay added on the new one (and count towards its freeze allowance).
        new.end_date += timedelta(days=old.frozen_days)
        new.frozen_days, new.freeze_allowance_days = old.frozen_days, old.freeze_allowance_days
        payment.offer_bonus = await self._offers.apply_bonus(pay.offer_id, [(new, target, applies[0])], scope)
        old.upgraded_to_id, old.updated_by = new.id, actor.user_id
        await self._repo.commit()
        return {"payment_id": payment.id, "receipt_no": payment.receipt_no, "subscription_ids": [new.id],
                "pt_subscription_ids": [], "amount": payment.amount,
                "discount_amount": payment.discount_amount, "paid_amount": payment.paid_amount,
                "balance_amount": payment.balance_amount}
