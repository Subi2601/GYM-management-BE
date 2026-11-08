"""Offers request/response handling — no business logic (OfferService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.offer import OfferCounts, OfferCreate, OfferResponse, OfferUpdate
from app.services.offer_service import OfferService


class OfferController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = OfferService(db)

    async def list_offers(self, scope: BranchScope, pagination: PaginationParams, search: str | None, tab: str,
                          sort_by: str | None, sort_dir: str) -> PaginatedEnvelope[OfferResponse]:
        rows, total = await self._service.list_offers(scope, offset=pagination.offset, limit=pagination.limit,
                                                      search=search, tab=tab, sort_by=sort_by, sort_dir=sort_dir)
        return PaginatedEnvelope.ok([OfferResponse(**r) for r in rows], total, pagination.page, pagination.page_size)

    async def counts(self, scope: BranchScope) -> ResponseEnvelope[OfferCounts]:
        return ResponseEnvelope.ok(OfferCounts(**await self._service.tab_counts(scope)))

    async def available(self, scope: BranchScope) -> ResponseEnvelope[list[OfferResponse]]:
        return ResponseEnvelope.ok([OfferResponse(**r) for r in await self._service.available(scope)])

    async def create_offer(self, body: OfferCreate, scope: BranchScope,
                           ctx: RequestContext) -> ResponseEnvelope[OfferResponse]:
        data = await self._service.create_offer(body, scope, ctx)
        return ResponseEnvelope.ok(OfferResponse(**data), message="Offer created")

    async def update_offer(self, offer_id: UUID, body: OfferUpdate, scope: BranchScope,
                           ctx: RequestContext) -> ResponseEnvelope[OfferResponse]:
        data = await self._service.update_offer(offer_id, body, scope, ctx)
        return ResponseEnvelope.ok(OfferResponse(**data), message="Offer updated")

    async def set_status(self, offer_id: UUID, is_active: bool, scope: BranchScope,
                         ctx: RequestContext) -> ResponseEnvelope[OfferResponse]:
        data = await self._service.set_status(offer_id, is_active, scope, ctx)
        return ResponseEnvelope.ok(OfferResponse(**data),
                                   message=f"Offer {'activated' if is_active else 'deactivated'}")
