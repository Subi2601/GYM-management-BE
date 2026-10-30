"""Diet plan request/response handling — no business logic (DietService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.diet import (DietPlanItemCreate, DietPlanResponse, DietPlanUpsert, EligibleMemberResponse,
                              ShareTextResponse)
from app.services.diet_service import DietService


class DietController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = DietService(db)

    async def list_eligible(self, scope: BranchScope, pagination: PaginationParams,
                            search: str | None) -> PaginatedEnvelope[EligibleMemberResponse]:
        rows, total = await self._service.list_eligible(scope, offset=pagination.offset, limit=pagination.limit,
                                                        search=search)
        return PaginatedEnvelope.ok([EligibleMemberResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def get_plan(self, member_id: UUID, scope: BranchScope) -> ResponseEnvelope[DietPlanResponse]:
        return ResponseEnvelope.ok(DietPlanResponse(**await self._service.get_plan(member_id, scope)))

    async def share_text(self, member_id: UUID, scope: BranchScope) -> ResponseEnvelope[ShareTextResponse]:
        return ResponseEnvelope.ok(ShareTextResponse(**await self._service.share_text(member_id, scope)))

    async def upsert_plan(self, member_id: UUID, body: DietPlanUpsert, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[DietPlanResponse]:
        data = await self._service.upsert_plan(member_id, body, scope, ctx)
        return ResponseEnvelope.ok(DietPlanResponse(**data), message="Diet plan saved")

    async def add_item(self, member_id: UUID, body: DietPlanItemCreate, scope: BranchScope,
                       ctx: RequestContext) -> ResponseEnvelope[DietPlanResponse]:
        data = await self._service.add_item(member_id, body, scope, ctx)
        return ResponseEnvelope.ok(DietPlanResponse(**data), message="Food added to meal")

    async def remove_item(self, member_id: UUID, item_id: UUID,
                          scope: BranchScope) -> ResponseEnvelope[DietPlanResponse]:
        data = await self._service.remove_item(member_id, item_id, scope)
        return ResponseEnvelope.ok(DietPlanResponse(**data), message="Food removed from meal")
