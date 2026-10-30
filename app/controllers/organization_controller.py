"""Organizations request/response handling — no business logic (OrganizationService)."""
from __future__ import annotations

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.organization import OrganizationCreate, OrganizationOnboardResponse, OrganizationResponse
from app.services.organization_service import OrganizationService


class OrganizationController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = OrganizationService(db)

    async def list_organizations(self, pagination: PaginationParams,
                                 search: str | None) -> PaginatedEnvelope[OrganizationResponse]:
        rows, total = await self._service.list_organizations(offset=pagination.offset, limit=pagination.limit,
                                                             search=search)
        return PaginatedEnvelope.ok([OrganizationResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def onboard(self, body: OrganizationCreate,
                      ctx: RequestContext) -> ResponseEnvelope[OrganizationOnboardResponse]:
        data = await self._service.onboard(body, ctx)
        return ResponseEnvelope.ok(OrganizationOnboardResponse(**data), message="Organization onboarded")
