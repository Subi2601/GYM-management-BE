"""Organization routes (SaaS onboarding) — platform superadmin only."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.organization_controller import OrganizationController
from app.dependencies import require_superadmin
from app.schemas.organization import OrganizationCreate, OrganizationOnboardResponse, OrganizationResponse

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


@router.get("", response_model=PaginatedEnvelope[OrganizationResponse],
            dependencies=[Depends(require_superadmin)])
async def list_organizations(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    controller: OrganizationController = Depends(),
):
    return await controller.list_organizations(pagination, search)


@router.post("", response_model=ResponseEnvelope[OrganizationOnboardResponse], status_code=201)
async def onboard_organization(body: OrganizationCreate, ctx: RequestContext = Depends(require_superadmin),
                               controller: OrganizationController = Depends()):
    return await controller.onboard(body, ctx)
