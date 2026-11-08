"""Renewal routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.renewal_controller import RenewalController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.common import SortDir
from app.schemas.renewal import RenewalCounts, RenewalRow

router = APIRouter(prefix="/api/v1/renewals", tags=["renewals"])

# "Due" = membership ends within this many days (the screen offers 7 / 15 / 30); not sent = the gym's
# renewal days (Gym settings).
_WITHIN = Query(default=None, ge=1, le=60)


@router.get("", response_model=PaginatedEnvelope[RenewalRow],
            dependencies=[Depends(require_permission("subscription:list"))])
async def list_renewals(
    pagination: PaginationParams = Depends(get_pagination),
    tab: Literal["due", "overdue", "reminded", "all"] = Query(default="due"),
    within: int | None = _WITHIN,
    search: str | None = Query(default=None, max_length=100),
    sort_by: Literal["member_name", "end_date", "reminded_at"] | None = Query(default=None),
    sort_dir: SortDir = Query(default="asc"),
    scope: BranchScope = Depends(get_branch_scope),
    controller: RenewalController = Depends(),
):
    return await controller.list_renewals(scope, pagination, within, tab, search, sort_by, sort_dir)


@router.get("/counts", response_model=ResponseEnvelope[RenewalCounts],
            dependencies=[Depends(require_permission("subscription:list"))])
async def renewal_counts(within: int | None = _WITHIN, scope: BranchScope = Depends(get_branch_scope),
                         controller: RenewalController = Depends()):
    return await controller.counts(scope, within)


@router.post("/{subscription_id}/remind", response_model=ResponseEnvelope[RenewalRow],
             dependencies=[Depends(require_permission("subscription:list"))])
async def mark_reminded(subscription_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user), controller: RenewalController = Depends()):
    """Records that the desk sent the WhatsApp reminder (the message itself opens in WhatsApp on the device)."""
    return await controller.mark_reminded(subscription_id, scope, ctx)
