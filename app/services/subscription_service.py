"""Subscriptions business logic — renewal board, history, atomic multi-plan enrolment, unpaid subscriptions."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import PaymentStatus, PlanServiceType, PTStatus, RenewalState, SubscriptionStatus
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.member import Member
from app.models.staff import Employee
from app.models.training import PTSubscription
from app.repositories.payment_repository import PaymentRepository
from app.repositories.subscription_repository import RENEWAL_WINDOW_DAYS, SubscriptionRepository
from app.repositories.training_repository import TrainingRepository
from app.services.payment_service import ZERO, PaymentService, allocate, money


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

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def subscription_out(s: Subscription, member_name: str, registration_id: str, member_phone: str,
                         plan: Plan, *, today: date) -> dict:
        return {
            "id": s.id, "branch_id": s.branch_id, "member_id": s.member_id, "member_name": member_name,
            "registration_id": registration_id, "member_phone": member_phone,
            "plan_id": plan.id, "plan_name": plan.name, "plan_type": plan.type, "service_type": plan.service_type,
            "price": plan.price, "start_date": s.start_date, "end_date": s.end_date,
            "discount_amount": s.discount_amount, "discount_reason": s.discount_reason, "status": s.status,
            "payment_id": s.payment_id, "payment_status": PaymentStatus.PAID if s.payment_id else PaymentStatus.PENDING,
            "renewal_state": renewal_state(s.end_date, today), "days_left": (s.end_date - today).days,
            "created_at": s.created_at, "updated_at": s.updated_at,
        }

    @staticmethod
    def _line(s: Subscription, plan: Plan) -> dict:
        return {"subscription_id": s.id, "plan_id": plan.id, "plan_name": plan.name, "plan_type": plan.type,
                "service_type": plan.service_type, "duration_days": plan.duration_days,
                "total_sessions": plan.total_sessions, "start_date": s.start_date, "end_date": s.end_date,
                "price": plan.price}

    # ── queries ──────────────────────────────────────────────────────────
    async def list_board(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                         renewal_state_filter: str | None) -> tuple[list[dict], int]:
        today = timeutil.today()
        rows, total = await self._repo.list_board(scope, offset=offset, limit=limit, today=today,
                                                  search=search, renewal_state=renewal_state_filter)
        return [self.subscription_out(*r, today=today) for r in rows], total

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

    async def _trainer(self, trainer_id: UUID | None, branch_id: UUID) -> Employee | None:
        if trainer_id is None:
            return None
        trainer = await self._training.get_active_trainer(trainer_id, branch_id)
        if trainer is None:
            raise NotFoundError("Trainer")
        return trainer

    async def _add_subscription(self, *, scope: BranchScope, branch_id: UUID, member: Member, plan: Plan,
                                start: date, discount, discount_reason: str | None, payment_id: UUID | None,
                                trainer: Employee | None, actor: RequestContext) -> tuple[Subscription, UUID | None]:
        """One subscription (+ PT record for PERSONAL_TRAINING plans). Caller commits."""
        sub = await self._repo.add(Subscription(
            organization_id=scope.organization_id, branch_id=branch_id, member_id=member.id, plan_id=plan.id,
            payment_id=payment_id, start_date=start, end_date=start + timedelta(days=plan.duration_days),
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
        trainer = await self._trainer(data.trainer_id, branch_id)
        start = data.start_date or timeutil.today()
        prices = [p.price for p in plans]
        gross = sum(prices, ZERO)
        pay = data.payment
        discount = money(pay.discount_amount)
        payment = await self._payments.build_payment(
            scope=scope, branch_id=branch_id, member_id=member.id, gross=gross, discount=discount,
            discount_reason=pay.discount_reason, paid=money(pay.paid_amount), mode=pay.payment_mode,
            balance_due_date=pay.balance_due_date, payment_date=pay.payment_date, actor=actor)
        sub_ids, pt_ids = [], []
        for plan, share in zip(plans, allocate(discount, prices)):
            sub, pt_id = await self._add_subscription(
                scope=scope, branch_id=branch_id, member=member, plan=plan, start=start, discount=share,
                discount_reason=pay.discount_reason, payment_id=payment.id, trainer=trainer, actor=actor)
            sub_ids.append(sub.id)
            if pt_id:
                pt_ids.append(pt_id)
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
