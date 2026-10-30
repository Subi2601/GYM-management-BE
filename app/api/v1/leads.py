"""Lead routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.lead_controller import LeadController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.lead import LeadConvertResponse, LeadCreate, LeadFollowUp, LeadResponse, LeadUpdate

router = APIRouter(prefix="/api/v1/leads", tags=["leads"])


@router.get("", response_model=PaginatedEnvelope[LeadResponse],
            dependencies=[Depends(require_permission("lead:list"))])
async def list_leads(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    filter: Literal["all", "followup", "rejected"] = Query(default="all"),
    scope: BranchScope = Depends(get_branch_scope),
    controller: LeadController = Depends(),
):
    return await controller.list_leads(scope, pagination, search, filter)


@router.get("/{lead_id}", response_model=ResponseEnvelope[LeadResponse],
            dependencies=[Depends(require_permission("lead:list"))])
async def get_lead(lead_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                   controller: LeadController = Depends()):
    return await controller.get_lead(lead_id, scope)


@router.post("", response_model=ResponseEnvelope[LeadResponse], status_code=201,
             dependencies=[Depends(require_permission("lead:create"))])
async def create_lead(body: LeadCreate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: LeadController = Depends()):
    return await controller.create_lead(body, scope, ctx)


@router.put("/{lead_id}", response_model=ResponseEnvelope[LeadResponse],
            dependencies=[Depends(require_permission("lead:update"))])
async def update_lead(lead_id: UUID, body: LeadUpdate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: LeadController = Depends()):
    return await controller.update_lead(lead_id, body, scope, ctx)


@router.delete("/{lead_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("lead:delete"))])
async def delete_lead(lead_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: LeadController = Depends()):
    return await controller.delete_lead(lead_id, scope, ctx)


@router.post("/{lead_id}/follow-up", response_model=ResponseEnvelope[LeadResponse],
             dependencies=[Depends(require_permission("lead:update"))])
async def add_follow_up(lead_id: UUID, body: LeadFollowUp, scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user), controller: LeadController = Depends()):
    return await controller.add_follow_up(lead_id, body, scope, ctx)


@router.post("/{lead_id}/convert", response_model=ResponseEnvelope[LeadConvertResponse],
             dependencies=[Depends(require_permission("lead:convert"))])
async def convert_lead(lead_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                       ctx: RequestContext = Depends(get_current_user), controller: LeadController = Depends()):
    return await controller.convert(lead_id, scope, ctx)
