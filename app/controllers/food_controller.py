"""Food catalogue request/response handling — no business logic (FoodService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FoodCategory
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.food import FoodItemCreate, FoodItemResponse
from app.services.food_service import FoodService


class FoodController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = FoodService(db)

    async def list_foods(self, scope: BranchScope, pagination: PaginationParams, category: FoodCategory | None,
                         search: str | None) -> PaginatedEnvelope[FoodItemResponse]:
        rows, total = await self._service.list_foods(scope, offset=pagination.offset, limit=pagination.limit,
                                                     category=category, search=search)
        return PaginatedEnvelope.ok([FoodItemResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def create_food(self, body: FoodItemCreate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[FoodItemResponse]:
        data = await self._service.create_food(body, scope, ctx)
        return ResponseEnvelope.ok(FoodItemResponse(**data), message="Food item added")

    async def delete_food(self, food_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete_food(food_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Food item deleted")
