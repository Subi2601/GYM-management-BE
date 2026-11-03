"""Plans request/response handling — no business logic (PlanService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PlanServiceType, PlanType
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.plan import PlanCounts, PlanCreate, PlanResponse, PlanUpdate
from app.services.plan_service import PlanService


class PlanController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = PlanService(db)

    async def list_plans(self, scope: BranchScope, pagination: PaginationParams, search: str | None,
                         plan_type: PlanType | None,
                         service_type: PlanServiceType | None, sort_by: str | None,
                         sort_dir: str) -> PaginatedEnvelope[PlanResponse]:
        rows, total = await self._service.list_plans(scope, offset=pagination.offset, limit=pagination.limit,
                                                     search=search, plan_type=plan_type,
                                                     service_type=service_type, sort_by=sort_by, sort_dir=sort_dir)
        return PaginatedEnvelope.ok([PlanResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def counts(self, scope: BranchScope) -> ResponseEnvelope[PlanCounts]:
        return ResponseEnvelope.ok(PlanCounts(**await self._service.tab_counts(scope)))

    async def get_plan(self, plan_id: UUID, scope: BranchScope) -> ResponseEnvelope[PlanResponse]:
        return ResponseEnvelope.ok(PlanResponse(**await self._service.get_plan(plan_id, scope)))

    async def create_plan(self, body: PlanCreate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[PlanResponse]:
        data = await self._service.create_plan(body, scope, ctx)
        return ResponseEnvelope.ok(PlanResponse(**data), message="Plan created")

    async def update_plan(self, plan_id: UUID, body: PlanUpdate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[PlanResponse]:
        data = await self._service.update_plan(plan_id, body, scope, ctx)
        return ResponseEnvelope.ok(PlanResponse(**data), message="Plan updated")

    async def delete_plan(self, plan_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete_plan(plan_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Plan deleted")
