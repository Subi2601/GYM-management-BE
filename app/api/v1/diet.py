"""Diet plan routes — registration + permission decorators only."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.diet_controller import DietController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.diet import (DietPlanItemCreate, DietPlanResponse, DietPlanUpsert, EligibleMemberResponse,
                              ShareTextResponse)

router = APIRouter(prefix="/api/v1/diet-plans", tags=["diet-plans"])


@router.get("/eligible-members", response_model=PaginatedEnvelope[EligibleMemberResponse],
            dependencies=[Depends(require_permission("diet:list"))])
async def list_eligible_members(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    scope: BranchScope = Depends(get_branch_scope),
    controller: DietController = Depends(),
):
    return await controller.list_eligible(scope, pagination, search)


@router.get("/member/{member_id}", response_model=ResponseEnvelope[DietPlanResponse],
            dependencies=[Depends(require_permission("diet:list"))])
async def get_diet_plan(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                        controller: DietController = Depends()):
    return await controller.get_plan(member_id, scope)


@router.get("/member/{member_id}/share-text", response_model=ResponseEnvelope[ShareTextResponse],
            dependencies=[Depends(require_permission("diet:list"))])
async def share_text(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                     controller: DietController = Depends()):
    return await controller.share_text(member_id, scope)


@router.put("/member/{member_id}", response_model=ResponseEnvelope[DietPlanResponse],
            dependencies=[Depends(require_permission("diet:manage"))])
async def upsert_diet_plan(member_id: UUID, body: DietPlanUpsert, scope: BranchScope = Depends(get_branch_scope),
                           ctx: RequestContext = Depends(get_current_user), controller: DietController = Depends()):
    return await controller.upsert_plan(member_id, body, scope, ctx)


@router.post("/member/{member_id}/items", response_model=ResponseEnvelope[DietPlanResponse], status_code=201,
             dependencies=[Depends(require_permission("diet:manage"))])
async def add_diet_item(member_id: UUID, body: DietPlanItemCreate, scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user), controller: DietController = Depends()):
    return await controller.add_item(member_id, body, scope, ctx)


@router.delete("/member/{member_id}/items/{item_id}", response_model=ResponseEnvelope[DietPlanResponse],
               dependencies=[Depends(require_permission("diet:manage"))])
async def remove_diet_item(member_id: UUID, item_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                           controller: DietController = Depends()):
    return await controller.remove_item(member_id, item_id, scope)
