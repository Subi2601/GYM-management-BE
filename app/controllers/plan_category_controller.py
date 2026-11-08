"""Plan category request/response handling — no business logic (PlanCategoryService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.plan_category import PlanCategoryCreate, PlanCategoryResponse, PlanCategoryUpdate
from app.services.plan_category_service import PlanCategoryService


class PlanCategoryController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = PlanCategoryService(db)

    async def list_categories(self, scope: BranchScope) -> ResponseEnvelope[list[PlanCategoryResponse]]:
        return ResponseEnvelope.ok([PlanCategoryResponse(**c) for c in await self._service.list_categories(scope)])

    async def create(self, body: PlanCategoryCreate, scope: BranchScope,
                     ctx: RequestContext) -> ResponseEnvelope[PlanCategoryResponse]:
        data = await self._service.create(body, scope, ctx)
        return ResponseEnvelope.ok(PlanCategoryResponse(**data), message=f"Category '{data['name']}' added")

    async def update(self, category_id: UUID, body: PlanCategoryUpdate, scope: BranchScope,
                     ctx: RequestContext) -> ResponseEnvelope[PlanCategoryResponse]:
        data = await self._service.update(category_id, body, scope, ctx)
        return ResponseEnvelope.ok(PlanCategoryResponse(**data), message="Category updated")

    async def reorder(self, ids: list[UUID], scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.reorder(ids, scope, ctx)
        return ResponseEnvelope.ok(None, message="Category order saved")

    async def delete(self, category_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete(category_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Category deleted")
