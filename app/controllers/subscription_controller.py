"""Subscriptions request/response handling — no business logic (SubscriptionService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.subscription import (EnrollRequest, EnrollResponse, SubscriptionCounts, SubscriptionCreate,
                                      SubscriptionDetail, SubscriptionResponse, UpgradeInfo, UpgradeRequest)
from app.services.subscription_service import SubscriptionService


class SubscriptionController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = SubscriptionService(db)

    async def list_board(self, scope: BranchScope, pagination: PaginationParams, search: str | None,
                         renewal_state: str | None, plan_id: UUID | None, sort_by: str | None,
                         sort_dir: str) -> PaginatedEnvelope[SubscriptionResponse]:
        rows, total = await self._service.list_board(scope, offset=pagination.offset, limit=pagination.limit,
                                                     search=search, renewal_state_filter=renewal_state,
                                                     plan_id=plan_id, sort_by=sort_by, sort_dir=sort_dir)
        return PaginatedEnvelope.ok([SubscriptionResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def counts(self, scope: BranchScope) -> ResponseEnvelope[SubscriptionCounts]:
        return ResponseEnvelope.ok(SubscriptionCounts(**await self._service.board_counts(scope)))

    async def list_for_member(self, member_id: UUID,
                              scope: BranchScope) -> ResponseEnvelope[list[SubscriptionResponse]]:
        rows = await self._service.list_for_member(member_id, scope)
        return ResponseEnvelope.ok([SubscriptionResponse(**r) for r in rows])

    async def get_detail(self, subscription_id: UUID, scope: BranchScope) -> ResponseEnvelope[SubscriptionDetail]:
        return ResponseEnvelope.ok(SubscriptionDetail(**await self._service.get_detail(subscription_id, scope)))

    async def enroll(self, body: EnrollRequest, scope: BranchScope,
                     ctx: RequestContext) -> ResponseEnvelope[EnrollResponse]:
        data = await self._service.enroll(body, scope, ctx)
        return ResponseEnvelope.ok(EnrollResponse(**data), message="Enrolment completed")

    async def upgrade_options(self, member_id: UUID, scope: BranchScope) -> ResponseEnvelope[UpgradeInfo]:
        return ResponseEnvelope.ok(UpgradeInfo(**await self._service.upgrade_options(member_id, scope)))

    async def upgrade(self, body: UpgradeRequest, scope: BranchScope,
                      ctx: RequestContext) -> ResponseEnvelope[EnrollResponse]:
        data = await self._service.upgrade(body, scope, ctx)
        return ResponseEnvelope.ok(EnrollResponse(**data), message="Plan upgraded")

    async def create_subscription(self, body: SubscriptionCreate, scope: BranchScope,
                                  ctx: RequestContext) -> ResponseEnvelope[SubscriptionDetail]:
        data = await self._service.create_subscription(body, scope, ctx)
        return ResponseEnvelope.ok(SubscriptionDetail(**data), message="Subscription created")
