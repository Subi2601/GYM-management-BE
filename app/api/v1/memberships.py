"""Membership action routes (freeze / transfer / cancel & refund) — registration + permission decorators only.

Reading what's possible needs `subscription:list`; every action is manager level (`membership:manage`).
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.membership_controller import MembershipController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user, get_pii_access
from app.schemas.membership import (ActionResult, CancelRequest, DocumentOut, FreezeAllowance, FreezeRequest,
                                    MembershipActions, RefundOut, TransferRequest)

router = APIRouter(prefix="/api/v1/memberships", tags=["memberships"])
_MANAGE = [Depends(require_permission("membership:manage"))]


@router.get("/member/{member_id}", response_model=ResponseEnvelope[MembershipActions],
            dependencies=[Depends(require_permission("subscription:list"))])
async def membership_actions(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                             controller: MembershipController = Depends()):
    """The membership running now and whether it can be frozen, transferred or refunded (and why not)."""
    return await controller.actions(member_id, scope)


@router.get("/member/{member_id}/documents", response_model=ResponseEnvelope[list[DocumentOut]],
            dependencies=[Depends(require_permission("subscription:list"))])
async def member_documents(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                           controller: MembershipController = Depends()):
    return await controller.documents(member_id, scope)


@router.get("/documents/{document_id}", dependencies=[Depends(require_permission("subscription:list"))])
async def download_document(document_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                            controller: MembershipController = Depends()):
    return await controller.download(document_id, scope)


@router.put("/{subscription_id}/freeze-allowance", response_model=ResponseEnvelope[MembershipActions],
            dependencies=_MANAGE)
async def set_freeze_allowance(subscription_id: UUID, body: FreezeAllowance,
                               scope: BranchScope = Depends(get_branch_scope),
                               ctx: RequestContext = Depends(get_current_user),
                               controller: MembershipController = Depends()):
    """This member's own freeze days (null = the gym's freeze days)."""
    return await controller.set_allowance(subscription_id, body, scope, ctx)


@router.post("/{subscription_id}/freeze", response_model=ResponseEnvelope[ActionResult], dependencies=_MANAGE)
async def freeze(subscription_id: UUID, body: FreezeRequest, scope: BranchScope = Depends(get_branch_scope),
                 ctx: RequestContext = Depends(get_current_user), controller: MembershipController = Depends()):
    return await controller.freeze(subscription_id, body, scope, ctx)


@router.post("/freezes/{freeze_id}/resume", response_model=ResponseEnvelope[ActionResult], dependencies=_MANAGE)
async def resume(freeze_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                 ctx: RequestContext = Depends(get_current_user), controller: MembershipController = Depends()):
    """End a freeze today (or drop one that hasn't started); unused days come off the end date."""
    return await controller.resume(freeze_id, scope, ctx)


@router.post("/{subscription_id}/transfer", response_model=ResponseEnvelope[ActionResult], dependencies=_MANAGE)
async def transfer(subscription_id: UUID, body: TransferRequest, scope: BranchScope = Depends(get_branch_scope),
                   ctx: RequestContext = Depends(get_current_user), controller: MembershipController = Depends()):
    return await controller.transfer(subscription_id, body, scope, ctx)


@router.post("/{subscription_id}/cancel", response_model=ResponseEnvelope[ActionResult], dependencies=_MANAGE)
async def cancel(subscription_id: UUID, body: CancelRequest, scope: BranchScope = Depends(get_branch_scope),
                 ctx: RequestContext = Depends(get_current_user), show_pii: bool = Depends(get_pii_access),
                 controller: MembershipController = Depends()):
    return await controller.cancel(subscription_id, body, scope, ctx, show_pii)


refunds_router = APIRouter(prefix="/api/v1/refunds", tags=["payments"])


@refunds_router.get("", response_model=PaginatedEnvelope[RefundOut],
                    dependencies=[Depends(require_permission("payment:list"))])
async def list_refunds(pagination: PaginationParams = Depends(get_pagination),
                       search: str | None = Query(default=None, max_length=100),
                       date_from: date | None = Query(default=None), date_to: date | None = Query(default=None),
                       scope: BranchScope = Depends(get_branch_scope), show_pii: bool = Depends(get_pii_access),
                       controller: MembershipController = Depends()):
    return await controller.list_refunds(scope, pagination, search, date_from, date_to, show_pii)
