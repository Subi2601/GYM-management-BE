"""Renewals request/response handling — no business logic (RenewalService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.renewal import RenewalCounts, RenewalRow
from app.services.renewal_service import RenewalService


class RenewalController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = RenewalService(db)

    async def list_renewals(self, scope: BranchScope, pagination: PaginationParams, within: int | None, tab: str,
                            search: str | None, sort_by: str | None, sort_dir: str) -> PaginatedEnvelope[RenewalRow]:
        rows, total = await self._service.list_renewals(scope, offset=pagination.offset, limit=pagination.limit,
                                                        within=within, tab=tab, search=search, sort_by=sort_by,
                                                        sort_dir=sort_dir)
        return PaginatedEnvelope.ok([RenewalRow(**r) for r in rows], total, pagination.page, pagination.page_size)

    async def counts(self, scope: BranchScope, within: int | None) -> ResponseEnvelope[RenewalCounts]:
        return ResponseEnvelope.ok(RenewalCounts(**await self._service.tab_counts(scope, within)))

    async def mark_reminded(self, subscription_id: UUID, scope: BranchScope,
                            ctx: RequestContext) -> ResponseEnvelope[RenewalRow]:
        data = await self._service.mark_reminded(subscription_id, scope, ctx)
        return ResponseEnvelope.ok(RenewalRow(**data), message=f"Reminder recorded for {data['member_name']}")
