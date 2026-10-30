"""Food catalogue routes — registration + permission decorators only."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.food_controller import FoodController
from app.core.enums import FoodCategory
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.food import FoodItemCreate, FoodItemResponse

router = APIRouter(prefix="/api/v1/food-items", tags=["food-items"])


@router.get("", response_model=PaginatedEnvelope[FoodItemResponse],
            dependencies=[Depends(require_permission("food:list"))])
async def list_foods(
    pagination: PaginationParams = Depends(get_pagination),
    category: FoodCategory | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    scope: BranchScope = Depends(get_branch_scope),
    controller: FoodController = Depends(),
):
    return await controller.list_foods(scope, pagination, category, search)


@router.post("", response_model=ResponseEnvelope[FoodItemResponse], status_code=201,
             dependencies=[Depends(require_permission("food:manage"))])
async def create_food(body: FoodItemCreate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: FoodController = Depends()):
    return await controller.create_food(body, scope, ctx)


@router.delete("/{food_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("food:manage"))])
async def delete_food(food_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: FoodController = Depends()):
    return await controller.delete_food(food_id, scope, ctx)
