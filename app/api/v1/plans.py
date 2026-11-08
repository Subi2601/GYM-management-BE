"""Plan routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.plan_controller import PlanController
from app.core.enums import PlanServiceType, PlanType
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.common import SortDir
from app.schemas.plan import PlanCounts, PlanCreate, PlanResponse, PlanUpdate

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])


@router.get("", response_model=PaginatedEnvelope[PlanResponse],
            dependencies=[Depends(require_permission("plan:list"))])
async def list_plans(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    type: PlanType | None = Query(default=None),
    service_type: PlanServiceType | None = Query(default=None),
    category_id: UUID | None = Query(default=None),
    active_only: bool = Query(default=False, description="Only plans shown for billing (plan and category on)"),
    status: Literal["active", "inactive"] | None = Query(default=None, description="Active / Inactive tab"),
    sort_by: Literal["name", "type", "service_type", "duration_days", "price",
                     "created_at"] | None = Query(default=None),
    sort_dir: SortDir = Query(default="desc"),
    scope: BranchScope = Depends(get_branch_scope),
    controller: PlanController = Depends(),
):
    return await controller.list_plans(scope, pagination, search, type, service_type, category_id, active_only,
                                       sort_by, sort_dir, status)


@router.get("/counts", response_model=ResponseEnvelope[PlanCounts],
            dependencies=[Depends(require_permission("plan:list"))])
async def plan_counts(search: str | None = Query(default=None, max_length=100),
                      category_id: UUID | None = Query(default=None),
                      scope: BranchScope = Depends(get_branch_scope), controller: PlanController = Depends()):
    return await controller.counts(scope, search, category_id)


@router.get("/{plan_id}", response_model=ResponseEnvelope[PlanResponse],
            dependencies=[Depends(require_permission("plan:list"))])
async def get_plan(plan_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                   controller: PlanController = Depends()):
    return await controller.get_plan(plan_id, scope)


@router.post("", response_model=ResponseEnvelope[PlanResponse], status_code=201,
             dependencies=[Depends(require_permission("plan:create"))])
async def create_plan(body: PlanCreate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: PlanController = Depends()):
    return await controller.create_plan(body, scope, ctx)


@router.put("/{plan_id}", response_model=ResponseEnvelope[PlanResponse],
            dependencies=[Depends(require_permission("plan:update"))])
async def update_plan(plan_id: UUID, body: PlanUpdate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: PlanController = Depends()):
    return await controller.update_plan(plan_id, body, scope, ctx)


@router.delete("/{plan_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("plan:delete"))])
async def delete_plan(plan_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: PlanController = Depends()):
    return await controller.delete_plan(plan_id, scope, ctx)
