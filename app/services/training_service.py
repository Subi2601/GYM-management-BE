"""Personal training business logic — subscribe, change trainer, log sessions (old logSession rules)."""
from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import PlanServiceType, PTStatus
from app.core.scope import BranchScope
from app.models.staff import Employee
from app.models.training import PTSessionLog, PTSubscription
from app.repositories.training_repository import TrainingRepository

NOT_ASSIGNED = "Not Assigned"


class TrainingService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = TrainingRepository(db)

    # ── output builders ──────────────────────────────────────────────────
    @staticmethod
    def pt_out(pt: PTSubscription, member_name: str, registration_id: str, member_phone: str,
               trainer_name: str | None, plan_name: str | None) -> dict:
        return {
            "id": pt.id, "branch_id": pt.branch_id, "member_id": pt.member_id, "member_name": member_name,
            "registration_id": registration_id, "member_phone": member_phone,
            "trainer_id": pt.trainer_id, "trainer_name": trainer_name or NOT_ASSIGNED,
            "plan_id": pt.plan_id, "plan_name": plan_name or "Custom Plan", "subscription_id": pt.subscription_id,
            "goal": pt.goal, "total_sessions": pt.total_sessions, "sessions_remaining": pt.sessions_remaining,
            "sessions_used": pt.total_sessions - pt.sessions_remaining,
            "start_date": pt.start_date, "expiry_date": pt.expiry_date, "is_paid": pt.is_paid, "status": pt.status,
            "created_at": pt.created_at, "updated_at": pt.updated_at,
        }

    @staticmethod
    def session_out(log: PTSessionLog, trainer_name: str | None) -> dict:
        return {
            "id": log.id, "pt_subscription_id": log.pt_subscription_id, "session_date": log.session_date,
            "trainer_id": log.trainer_id, "trainer_name": trainer_name or NOT_ASSIGNED,
            "trainer_verified": log.trainer_verified, "client_verified": log.client_verified, "notes": log.notes,
            "sessions_remaining_after": log.sessions_remaining_after,
            "created_at": log.created_at, "updated_at": log.updated_at,
        }

    # ── queries ──────────────────────────────────────────────────────────
    async def list_pt(self, scope: BranchScope, *, offset: int, limit: int, status: PTStatus | None,
                      paid_only: bool, search: str | None, trainer_id: UUID | None,
                      member_id: UUID | None, sort_by: str | None, sort_dir: str) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_pt(scope, offset=offset, limit=limit, status=status,
                                               paid_only=paid_only, search=search, trainer_id=trainer_id,
                                               member_id=member_id, sort_by=sort_by, sort_dir=sort_dir)
        return [self.pt_out(*r) for r in rows], total

    async def status_counts(self, scope: BranchScope, *, paid_only: bool) -> dict:
        return await self._repo.status_counts(scope, paid_only=paid_only)

    async def get_pt(self, pt_id: UUID, scope: BranchScope) -> dict:
        row = await self._repo.get_pt_row(pt_id, scope)
        if row is None:
            raise NotFoundError("PT subscription")
        return self.pt_out(*row)

    async def sessions(self, pt_id: UUID, scope: BranchScope) -> list[dict]:
        if await self._repo.get_pt(pt_id, scope) is None:
            raise NotFoundError("PT subscription")
        return [self.session_out(*r) for r in await self._repo.list_sessions(pt_id, scope)]

    # ── helpers ──────────────────────────────────────────────────────────
    async def _trainer(self, trainer_id: UUID, branch_id: UUID) -> Employee:
        trainer = await self._repo.get_active_trainer(trainer_id, branch_id)
        if trainer is None:
            raise NotFoundError("Trainer")
        return trainer

    async def _pt_in_branch(self, pt_id: UUID, scope: BranchScope, branch_id: UUID) -> PTSubscription:
        pt = await self._repo.get_pt(pt_id, scope, for_update=True)
        if pt is None or pt.branch_id != branch_id:
            raise NotFoundError("PT subscription")
        return pt

    # ── commands ─────────────────────────────────────────────────────────
    async def subscribe(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        member = await self._repo.get_member(data.member_id, scope)
        if member is None or member.branch_id != branch_id:
            raise NotFoundError("Member")
        plan = await self._repo.get_plan(data.plan_id, scope)
        if plan is None or plan.branch_id != branch_id:
            raise NotFoundError("Plan")
        if plan.service_type != PlanServiceType.PERSONAL_TRAINING:
            raise BadRequestError("Plan is not a personal training plan")
        if plan.total_sessions < 1:
            raise BadRequestError("Personal training plan has no sessions configured")
        trainer = await self._trainer(data.trainer_id, branch_id)
        start = data.start_date or timeutil.today()
        pt = await self._repo.add(PTSubscription(
            organization_id=scope.organization_id, branch_id=branch_id, member_id=member.id,
            trainer_id=trainer.id, plan_id=plan.id, goal=data.goal,
            total_sessions=plan.total_sessions, sessions_remaining=plan.total_sessions,
            start_date=start, expiry_date=start + timedelta(days=plan.duration_days),
            is_paid=False, status=PTStatus.ACTIVE, created_by=actor.user_id,
        ))
        await self._repo.commit()
        return await self.get_pt(pt.id, scope)

    async def change_trainer(self, pt_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        pt = await self._pt_in_branch(pt_id, scope, branch_id)
        trainer = await self._trainer(data.trainer_id, branch_id)
        pt.trainer_id = trainer.id
        pt.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_pt(pt.id, scope)

    async def log_session(self, pt_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        pt = await self._pt_in_branch(pt_id, scope, branch_id)
        new_trainer = await self._trainer(data.trainer_id, branch_id) if data.trainer_id else None
        today = timeutil.today()
        session_date = data.session_date or today
        if pt.status != PTStatus.ACTIVE:
            raise BadRequestError("PT subscription is not active")
        if not pt.is_paid:
            raise BadRequestError("PT subscription is not paid yet — record the payment first")
        if pt.sessions_remaining <= 0:
            raise BadRequestError("No sessions remaining in this plan")
        if pt.expiry_date < today:
            pt.status = PTStatus.EXPIRED            # persisted, as the old service intended
            pt.updated_by = actor.user_id
            await self._repo.commit()
            raise BadRequestError("PT plan has expired")
        if session_date > today:
            raise BadRequestError("Session date cannot be in the future")
        if session_date < pt.start_date:
            raise BadRequestError("Session date is before the PT start date")
        if new_trainer is not None:
            pt.trainer_id = new_trainer.id
        pt.sessions_remaining -= 1
        if pt.sessions_remaining == 0:
            pt.status = PTStatus.COMPLETED
        pt.updated_by = actor.user_id
        await self._repo.add(PTSessionLog(
            organization_id=scope.organization_id, branch_id=branch_id, pt_subscription_id=pt.id,
            trainer_id=pt.trainer_id, session_date=session_date, trainer_verified=data.trainer_verified,
            client_verified=data.client_verified, notes=data.notes,
            sessions_remaining_after=pt.sessions_remaining, created_by=actor.user_id,
        ))
        await self._repo.commit()
        return await self.get_pt(pt.id, scope)
