"""Plan category routes — registration + permission decorators only."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.plan_category_controller import PlanCategoryController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.plan_category import (PlanCategoryCreate, PlanCategoryReorder, PlanCategoryResponse,
                                       PlanCategoryUpdate)

router = APIRouter(prefix="/api/v1/plan-categories", tags=["plans"])


@router.get("", response_model=ResponseEnvelope[list[PlanCategoryResponse]],
            dependencies=[Depends(require_permission("plan:list"))])
async def list_categories(scope: BranchScope = Depends(get_branch_scope),
                          controller: PlanCategoryController = Depends()):
    """The organization's categories in tab order, with plan counts for the selected branch(es)."""
    return await controller.list_categories(scope)


@router.post("", response_model=ResponseEnvelope[PlanCategoryResponse], status_code=201,
             dependencies=[Depends(require_permission("plan:create"))])
async def create_category(body: PlanCategoryCreate, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          controller: PlanCategoryController = Depends()):
    return await controller.create(body, scope, ctx)


@router.put("/order", response_model=ResponseEnvelope[None],
            dependencies=[Depends(require_permission("plan:update"))])
async def reorder_categories(body: PlanCategoryReorder, scope: BranchScope = Depends(get_branch_scope),
                             ctx: RequestContext = Depends(get_current_user),
                             controller: PlanCategoryController = Depends()):
    return await controller.reorder(body.ids, scope, ctx)


@router.put("/{category_id}", response_model=ResponseEnvelope[PlanCategoryResponse],
            dependencies=[Depends(require_permission("plan:update"))])
async def update_category(category_id: UUID, body: PlanCategoryUpdate, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          controller: PlanCategoryController = Depends()):
    return await controller.update(category_id, body, scope, ctx)


@router.delete("/{category_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("plan:delete"))])
async def delete_category(category_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          controller: PlanCategoryController = Depends()):
    return await controller.delete(category_id, scope, ctx)
