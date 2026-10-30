"""Subscription routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.subscription_controller import SubscriptionController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.subscription import (EnrollRequest, EnrollResponse, SubscriptionCreate, SubscriptionDetail,
                                      SubscriptionResponse)

router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])


@router.get("", response_model=PaginatedEnvelope[SubscriptionResponse],
            dependencies=[Depends(require_permission("subscription:list"))])
async def list_subscriptions(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    renewal_state: Literal["EXPIRED", "EXPIRING", "NONE"] | None = Query(default=None),
    scope: BranchScope = Depends(get_branch_scope),
    controller: SubscriptionController = Depends(),
):
    """Renewal board — latest subscription per member."""
    return await controller.list_board(scope, pagination, search, renewal_state)


@router.post("/enroll", response_model=ResponseEnvelope[EnrollResponse], status_code=201,
             dependencies=[Depends(require_permission("subscription:create"))])
async def enroll(body: EnrollRequest, scope: BranchScope = Depends(get_branch_scope),
                 ctx: RequestContext = Depends(get_current_user), controller: SubscriptionController = Depends()):
    return await controller.enroll(body, scope, ctx)


@router.get("/member/{member_id}", response_model=ResponseEnvelope[list[SubscriptionResponse]],
            dependencies=[Depends(require_permission("subscription:list"))])
async def member_subscriptions(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                               controller: SubscriptionController = Depends()):
    return await controller.list_for_member(member_id, scope)


@router.get("/{subscription_id}", response_model=ResponseEnvelope[SubscriptionDetail],
            dependencies=[Depends(require_permission("subscription:list"))])
async def get_subscription(subscription_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                           controller: SubscriptionController = Depends()):
    return await controller.get_detail(subscription_id, scope)


@router.post("", response_model=ResponseEnvelope[SubscriptionDetail], status_code=201,
             dependencies=[Depends(require_permission("subscription:create"))])
async def create_subscription(body: SubscriptionCreate, scope: BranchScope = Depends(get_branch_scope),
                              ctx: RequestContext = Depends(get_current_user),
                              controller: SubscriptionController = Depends()):
    return await controller.create_subscription(body, scope, ctx)
