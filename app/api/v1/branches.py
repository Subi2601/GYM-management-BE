"""Branch routes — registration + permission decorators only.

Branch endpoints manage the branch scope itself, so they take the caller's organization from the
token (get_current_user) instead of get_branch_scope.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.branch_controller import BranchController
from app.dependencies import get_current_user
from app.schemas.organization import BranchCreate, BranchPasswordReset, BranchResponse, BranchUpdate

router = APIRouter(prefix="/api/v1/branches", tags=["branches"])


@router.get("", response_model=PaginatedEnvelope[BranchResponse],
            dependencies=[Depends(require_permission("branch:list"))])
async def list_branches(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    ctx: RequestContext = Depends(get_current_user),
    controller: BranchController = Depends(),
):
    return await controller.list_branches(ctx, pagination, search)


@router.get("/{branch_id}", response_model=ResponseEnvelope[BranchResponse],
            dependencies=[Depends(require_permission("branch:list"))])
async def get_branch(branch_id: UUID, ctx: RequestContext = Depends(get_current_user),
                     controller: BranchController = Depends()):
    return await controller.get_branch(branch_id, ctx)


@router.post("", response_model=ResponseEnvelope[BranchResponse], status_code=201,
             dependencies=[Depends(require_permission("branch:create"))])
async def create_branch(body: BranchCreate, ctx: RequestContext = Depends(get_current_user),
                        controller: BranchController = Depends()):
    return await controller.create_branch(body, ctx)


@router.put("/{branch_id}", response_model=ResponseEnvelope[BranchResponse],
            dependencies=[Depends(require_permission("branch:update"))])
async def update_branch(branch_id: UUID, body: BranchUpdate, ctx: RequestContext = Depends(get_current_user),
                        controller: BranchController = Depends()):
    return await controller.update_branch(branch_id, body, ctx)


@router.delete("/{branch_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("branch:delete"))])
async def delete_branch(branch_id: UUID, ctx: RequestContext = Depends(get_current_user),
                        controller: BranchController = Depends()):
    return await controller.delete_branch(branch_id, ctx)


@router.post("/{branch_id}/reset-login-password", response_model=ResponseEnvelope[None],
             dependencies=[Depends(require_permission("branch:update"))])
async def reset_login_password(branch_id: UUID, body: BranchPasswordReset,
                               ctx: RequestContext = Depends(get_current_user),
                               controller: BranchController = Depends()):
    return await controller.reset_login_password(branch_id, body, ctx)
