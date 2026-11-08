"""Offer routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.offer_controller import OfferController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.common import SortDir
from app.schemas.offer import OfferCounts, OfferCreate, OfferResponse, OfferStatusUpdate, OfferUpdate

router = APIRouter(prefix="/api/v1/offers", tags=["offers"])


@router.get("", response_model=PaginatedEnvelope[OfferResponse],
            dependencies=[Depends(require_permission("offer:list"))])
async def list_offers(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    tab: Literal["active", "inactive", "all"] = Query(default="active"),
    sort_by: Literal["name", "discount_percent", "valid_to", "created_at"] | None = Query(default=None),
    sort_dir: SortDir = Query(default="asc"),
    scope: BranchScope = Depends(get_branch_scope),
    controller: OfferController = Depends(),
):
    return await controller.list_offers(scope, pagination, search, tab, sort_by, sort_dir)


@router.get("/counts", response_model=ResponseEnvelope[OfferCounts],
            dependencies=[Depends(require_permission("offer:list"))])
async def offer_counts(scope: BranchScope = Depends(get_branch_scope), controller: OfferController = Depends()):
    return await controller.counts(scope)


@router.get("/available", response_model=ResponseEnvelope[list[OfferResponse]],
            dependencies=[Depends(require_permission("offer:list"))])
async def available_offers(scope: BranchScope = Depends(get_branch_scope), controller: OfferController = Depends()):
    """Active offers valid today — the billing screens' "Offer" dropdown."""
    return await controller.available(scope)


@router.post("", response_model=ResponseEnvelope[OfferResponse], status_code=201,
             dependencies=[Depends(require_permission("offer:manage"))])
async def create_offer(body: OfferCreate, scope: BranchScope = Depends(get_branch_scope),
                       ctx: RequestContext = Depends(get_current_user), controller: OfferController = Depends()):
    return await controller.create_offer(body, scope, ctx)


@router.put("/{offer_id}", response_model=ResponseEnvelope[OfferResponse],
            dependencies=[Depends(require_permission("offer:manage"))])
async def update_offer(offer_id: UUID, body: OfferUpdate, scope: BranchScope = Depends(get_branch_scope),
                       ctx: RequestContext = Depends(get_current_user), controller: OfferController = Depends()):
    return await controller.update_offer(offer_id, body, scope, ctx)


@router.patch("/{offer_id}/status", response_model=ResponseEnvelope[OfferResponse],
              dependencies=[Depends(require_permission("offer:manage"))])
async def set_offer_status(offer_id: UUID, body: OfferStatusUpdate, scope: BranchScope = Depends(get_branch_scope),
                           ctx: RequestContext = Depends(get_current_user), controller: OfferController = Depends()):
    return await controller.set_status(offer_id, body.is_active, scope, ctx)
