"""Member routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.member_controller import MemberController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user, get_pii_access
from app.schemas.common import CodeResponse
from app.schemas.member import MemberCounts, MemberCreate, MemberResponse, MemberUpdate

router = APIRouter(prefix="/api/v1/members", tags=["members"])


@router.get("", response_model=PaginatedEnvelope[MemberResponse],
            dependencies=[Depends(require_permission("member:list"))])
async def list_members(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    filter: Literal["all", "active", "inactive", "expiring"] = Query(default="all"),
    plan_id: UUID | None = Query(default=None),
    scope: BranchScope = Depends(get_branch_scope),
    show_pii: bool = Depends(get_pii_access),
    controller: MemberController = Depends(),
):
    return await controller.list_members(scope, pagination, search, filter, plan_id, show_pii)


@router.get("/next-registration-id", response_model=ResponseEnvelope[CodeResponse],
            dependencies=[Depends(require_permission("member:create"))])
async def next_registration_id(scope: BranchScope = Depends(get_branch_scope),
                               controller: MemberController = Depends()):
    return await controller.next_registration_id(scope)


@router.get("/counts", response_model=ResponseEnvelope[MemberCounts],
            dependencies=[Depends(require_permission("member:list"))])
async def member_counts(scope: BranchScope = Depends(get_branch_scope),
                        controller: MemberController = Depends()):
    return await controller.counts(scope)


@router.get("/{member_id}", response_model=ResponseEnvelope[MemberResponse],
            dependencies=[Depends(require_permission("member:list"))])
async def get_member(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                     show_pii: bool = Depends(get_pii_access), controller: MemberController = Depends()):
    return await controller.get_member(member_id, scope, show_pii)


@router.post("", response_model=ResponseEnvelope[MemberResponse], status_code=201,
             dependencies=[Depends(require_permission("member:create"))])
async def create_member(body: MemberCreate, scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user),
                        show_pii: bool = Depends(get_pii_access), controller: MemberController = Depends()):
    return await controller.create_member(body, scope, ctx, show_pii)


@router.put("/{member_id}", response_model=ResponseEnvelope[MemberResponse],
            dependencies=[Depends(require_permission("member:update"))])
async def update_member(member_id: UUID, body: MemberUpdate, scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user),
                        show_pii: bool = Depends(get_pii_access), controller: MemberController = Depends()):
    return await controller.update_member(member_id, body, scope, ctx, show_pii)


@router.delete("/{member_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("member:delete"))])
async def delete_member(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user), controller: MemberController = Depends()):
    return await controller.delete_member(member_id, scope, ctx)
