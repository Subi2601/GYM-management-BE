"""Plans business logic — type/service-type rules, delete protection."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PlanServiceType, PlanType
from app.core.scope import BranchScope
from app.models.billing import Plan
from app.repositories.plan_repository import PlanRepository

_FIELDS = ("name", "type", "service_type", "duration_days", "price", "total_sessions", "description")
_REQUIRED = ("name", "type", "service_type", "duration_days", "price", "total_sessions")


def _check_rules(plan_type: PlanType, service_type: PlanServiceType, total_sessions: int) -> None:
    if plan_type == PlanType.MEMBERSHIP and service_type != PlanServiceType.GENERAL:
        raise ValidationError("A MEMBERSHIP plan must have service type GENERAL")
    if service_type == PlanServiceType.PERSONAL_TRAINING and total_sessions < 1:
        raise ValidationError("A PERSONAL_TRAINING plan needs at least 1 session")


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


class PlanService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = PlanRepository(db)

    @staticmethod
    def plan_out(p: Plan) -> dict:
        return {"id": p.id, "branch_id": p.branch_id, "name": p.name, "type": p.type,
                "service_type": p.service_type, "duration_days": p.duration_days, "price": float(p.price),
                "total_sessions": p.total_sessions, "description": p.description,
                "created_at": p.created_at, "updated_at": p.updated_at}

    # ── queries ──────────────────────────────────────────────────────────
    async def list_plans(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                         plan_type: PlanType | None,
                         service_type: PlanServiceType | None) -> tuple[list[dict], int]:
        plans, total = await self._repo.list_plans(scope, offset=offset, limit=limit, search=search,
                                                   plan_type=plan_type, service_type=service_type)
        return [self.plan_out(p) for p in plans], total

    async def get_plan(self, plan_id: UUID, scope: BranchScope) -> dict:
        return self.plan_out(await self._get(plan_id, scope))

    async def _get(self, plan_id: UUID, scope: BranchScope) -> Plan:
        plan = await self._repo.get_plan(plan_id, scope)
        if plan is None:
            raise NotFoundError("Plan")
        return plan

    # ── commands ─────────────────────────────────────────────────────────
    async def create_plan(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        plan_type, service_type = PlanType(data.type), PlanServiceType(data.service_type)
        _check_rules(plan_type, service_type, data.total_sessions)
        plan = await self._repo.add(Plan(
            organization_id=scope.organization_id, branch_id=branch_id, name=data.name, type=plan_type,
            service_type=service_type, duration_days=data.duration_days, price=_money(data.price),
            total_sessions=data.total_sessions, description=data.description, created_by=actor.user_id))
        await self._repo.commit()
        return await self.get_plan(plan.id, scope)

    async def update_plan(self, plan_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        plan = await self._get(plan_id, scope)
        sent = data.model_fields_set
        changes = {f: getattr(data, f) for f in _FIELDS if f in sent}
        changes = {f: v for f, v in changes.items() if not (v is None and f in _REQUIRED)}
        plan_type = PlanType(changes.get("type", plan.type))
        service_type = PlanServiceType(changes.get("service_type", plan.service_type))
        _check_rules(plan_type, service_type, changes.get("total_sessions", plan.total_sessions))
        for field, value in changes.items():
            if field == "price":
                value = _money(value)
            elif field == "type":
                value = plan_type
            elif field == "service_type":
                value = service_type
            setattr(plan, field, value)
        plan.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_plan(plan.id, scope)

    async def delete_plan(self, plan_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        scope.require_branch()
        plan = await self._get(plan_id, scope)
        if await self._repo.is_in_use(plan.id):
            raise BadRequestError("Cannot delete plan: subscriptions exist for this plan")
        plan.soft_delete(actor.user_id)
        await self._repo.commit()
