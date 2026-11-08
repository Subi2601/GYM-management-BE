"""Plans business logic — type / billing / group rules, deactivate instead of delete when in use."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import MEMBERSHIP_PLAN_TYPES, PlanServiceType, PlanType
from app.core.scope import BranchScope
from app.models.billing import Plan, default_upgrade_window
from app.repositories.plan_repository import PlanRepository
from app.services.plan_category_service import PlanCategoryService

_FIELDS = ("name", "category_id", "type", "service_type", "duration_months", "duration_days", "price",
           "total_sessions", "group_size", "free_members", "id_check", "all_branches", "upgrade_window_days", "is_active",
           "description", "refundable", "refund_window_days")
_REQUIRED = ("name", "category_id", "type", "service_type", "price", "total_sessions", "group_size",
             "free_members", "all_branches", "is_active", "refundable")
# Rough days per month — only for sorting / display; the end date uses real calendar months.
DAYS_PER_MONTH = 30



def _check_rules(p: dict) -> None:
    plan_type, service_type = p["type"], p["service_type"]
    if plan_type in MEMBERSHIP_PLAN_TYPES and service_type != PlanServiceType.GENERAL:
        raise ValidationError(f"A {plan_type.value} plan must have service type GENERAL")
    if plan_type == PlanType.CUSTOM and p["total_sessions"]:
        raise ValidationError("A CUSTOM plan has no sessions")
    if service_type == PlanServiceType.PERSONAL_TRAINING and p["total_sessions"] < 1:
        raise ValidationError("A PERSONAL_TRAINING plan needs at least 1 session")
    if not p["duration_months"] and not p["duration_days"]:
        raise ValidationError("Set the duration in months or in days")
    if p["duration_months"] and plan_type == PlanType.CUSTOM:
        raise ValidationError("A CUSTOM plan is priced per day, so its duration is in days")
    if p["group_size"] > 1 and plan_type != PlanType.MEMBERSHIP:
        raise ValidationError("Only membership plans can cover more than one member")
    if p["free_members"] >= p["group_size"] and p["free_members"]:
        raise ValidationError("Free members must be fewer than the members the plan covers")


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


class PlanService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = PlanRepository(db)
        self._categories = PlanCategoryService(db)

    @staticmethod
    def plan_out(p: Plan, category_name: str) -> dict:
        return {"id": p.id, "branch_id": p.branch_id, "name": p.name, "category_id": p.category_id,
                "category_name": category_name, "type": p.type, "service_type": p.service_type,
                "duration_months": p.duration_months, "duration_days": p.duration_days, "price": float(p.price),
                "total_sessions": p.total_sessions, "group_size": p.group_size, "free_members": p.free_members,
                "id_check": p.id_check, "all_branches": p.all_branches,
                "upgrade_window_days": p.upgrade_window_days, "is_active": p.is_active,
                "refundable": p.refundable, "refund_window_days": p.refund_window_days,
                "description": p.description, "created_at": p.created_at, "updated_at": p.updated_at}

    # ── queries ──────────────────────────────────────────────────────────
    async def list_plans(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                         plan_type: PlanType | None, service_type: PlanServiceType | None,
                         category_id: UUID | None, active_only: bool, sort_by: str | None,
                         sort_dir: str, status: str | None = None) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_plans(scope, offset=offset, limit=limit, search=search,
                                                  plan_type=plan_type, service_type=service_type,
                                                  category_id=category_id, active_only=active_only,
                                                  status=status, sort_by=sort_by, sort_dir=sort_dir)
        return [self.plan_out(*r) for r in rows], total

    async def tab_counts(self, scope: BranchScope, *, search: str | None = None,
                         category_id: UUID | None = None) -> dict:
        return await self._repo.tab_counts(scope, search=search, category_id=category_id)

    async def get_plan(self, plan_id: UUID, scope: BranchScope) -> dict:
        row = await self._repo.get_plan_row(plan_id, scope)
        if row is None:
            raise NotFoundError("Plan")
        return self.plan_out(*row)

    async def _get(self, plan_id: UUID, scope: BranchScope) -> Plan:
        plan = await self._repo.get_plan(plan_id, scope)
        if plan is None:
            raise NotFoundError("Plan")
        return plan

    # ── commands ─────────────────────────────────────────────────────────
    @staticmethod
    def _normalise(p: dict) -> dict:
        p["type"], p["service_type"] = PlanType(p["type"]), PlanServiceType(p["service_type"])
        if p["duration_months"]:
            p["duration_days"] = p["duration_months"] * DAYS_PER_MONTH
        p["id_check"] = (p.get("id_check") or "").strip() or None
        if p.get("upgrade_window_days") is None:
            p["upgrade_window_days"] = default_upgrade_window(p["duration_months"], p["duration_days"])
        if not p.get("refundable"):
            p["refundable"], p["refund_window_days"] = False, None
        return p

    async def create_plan(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        await self._categories.require(data.category_id, scope.organization_id)
        p = self._normalise({f: getattr(data, f) for f in _FIELDS})
        _check_rules(p)
        p["price"] = _money(p["price"])
        plan = await self._repo.add(Plan(organization_id=scope.organization_id, branch_id=branch_id, **p,
                                         created_by=actor.user_id))
        await self._repo.commit()
        return await self.get_plan(plan.id, scope)

    async def update_plan(self, plan_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        plan = await self._get(plan_id, scope)
        sent = data.model_fields_set
        changes = {f: getattr(data, f) for f in _FIELDS if f in sent}
        changes = {f: v for f, v in changes.items() if not (v is None and f in _REQUIRED)}
        if "category_id" in changes:
            await self._categories.require(changes["category_id"], scope.organization_id)
        # Months and days are alternatives: sending one clears the other.
        if changes.get("duration_months"):
            changes["duration_days"] = None
        elif changes.get("duration_days") and "duration_months" not in changes:
            changes["duration_months"] = None
        merged = {f: changes.get(f, getattr(plan, f)) for f in _FIELDS}
        p = self._normalise(merged)
        _check_rules(p)
        p["price"] = _money(p["price"])
        for field in _FIELDS:
            setattr(plan, field, p[field])
        plan.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_plan(plan.id, scope)

    async def delete_plan(self, plan_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        scope.require_branch()
        plan = await self._get(plan_id, scope)
        if await self._repo.is_in_use(plan.id):
            raise BadRequestError("Members are on this plan, so it can't be deleted. Make it inactive instead")
        plan.soft_delete(actor.user_id)
        await self._repo.commit()
