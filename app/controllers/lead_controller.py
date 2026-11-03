"""Leads request/response handling — no business logic (LeadService)."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LeadStatus
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.lead import LeadConvertResponse, LeadCounts, LeadCreate, LeadFollowUp, LeadResponse, LeadUpdate
from app.services.lead_service import LeadService


class LeadController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = LeadService(db)

    async def list_leads(self, scope: BranchScope, pagination: PaginationParams, search: str | None,
                         lead_filter: str | None, status: LeadStatus | None, follow_up_from: date | None,
                         follow_up_to: date | None, sort_by: str | None,
                         sort_dir: str) -> PaginatedEnvelope[LeadResponse]:
        rows, total = await self._service.list_leads(scope, offset=pagination.offset, limit=pagination.limit,
                                                     search=search, lead_filter=lead_filter, status=status,
                                                     follow_up_from=follow_up_from, follow_up_to=follow_up_to,
                                                     sort_by=sort_by, sort_dir=sort_dir)
        return PaginatedEnvelope.ok([LeadResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def counts(self, scope: BranchScope) -> ResponseEnvelope[LeadCounts]:
        return ResponseEnvelope.ok(LeadCounts(**await self._service.tab_counts(scope)))

    async def get_lead(self, lead_id: UUID, scope: BranchScope) -> ResponseEnvelope[LeadResponse]:
        return ResponseEnvelope.ok(LeadResponse(**await self._service.get_lead(lead_id, scope)))

    async def create_lead(self, body: LeadCreate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[LeadResponse]:
        data = await self._service.create_lead(body, scope, ctx)
        return ResponseEnvelope.ok(LeadResponse(**data), message="Lead created")

    async def update_lead(self, lead_id: UUID, body: LeadUpdate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[LeadResponse]:
        data = await self._service.update_lead(lead_id, body, scope, ctx)
        return ResponseEnvelope.ok(LeadResponse(**data), message="Lead updated")

    async def delete_lead(self, lead_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete_lead(lead_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Lead deleted")

    async def add_follow_up(self, lead_id: UUID, body: LeadFollowUp, scope: BranchScope,
                            ctx: RequestContext) -> ResponseEnvelope[LeadResponse]:
        data = await self._service.add_follow_up(lead_id, body, scope, ctx)
        return ResponseEnvelope.ok(LeadResponse(**data), message="Follow-up recorded")

    async def convert(self, lead_id: UUID, scope: BranchScope,
                      ctx: RequestContext) -> ResponseEnvelope[LeadConvertResponse]:
        data = await self._service.convert(lead_id, scope, ctx)
        return ResponseEnvelope.ok(LeadConvertResponse(**data),
                                   message=f"Lead converted to member {data['registration_id']}")
