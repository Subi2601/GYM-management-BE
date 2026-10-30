"""Payment routes — registration + permission decorators only."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.payment_controller import PaymentController
from app.core.enums import PaymentMode
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.payment import InvoiceResponse, PaymentCreate, PaymentResponse, PaymentStats

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


@router.get("", response_model=PaginatedEnvelope[PaymentResponse],
            dependencies=[Depends(require_permission("payment:list"))])
async def list_payments(
    pagination: PaginationParams = Depends(get_pagination),
    search: str | None = Query(default=None, max_length=100),
    payment_mode: PaymentMode | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    scope: BranchScope = Depends(get_branch_scope),
    controller: PaymentController = Depends(),
):
    return await controller.list_payments(scope, pagination, search, payment_mode, date_from, date_to)


@router.get("/stats", response_model=ResponseEnvelope[PaymentStats],
            dependencies=[Depends(require_permission("payment:stats"))])
async def payment_stats(scope: BranchScope = Depends(get_branch_scope), controller: PaymentController = Depends()):
    return await controller.stats(scope)


@router.get("/{payment_id}/invoice", response_model=ResponseEnvelope[InvoiceResponse],
            dependencies=[Depends(require_permission("payment:invoice"))])
async def payment_invoice(payment_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                          controller: PaymentController = Depends()):
    return await controller.invoice(payment_id, scope)


@router.post("", response_model=ResponseEnvelope[PaymentResponse], status_code=201,
             dependencies=[Depends(require_permission("payment:create"))])
async def create_payment(body: PaymentCreate, scope: BranchScope = Depends(get_branch_scope),
                         ctx: RequestContext = Depends(get_current_user), controller: PaymentController = Depends()):
    return await controller.create_payment(body, scope, ctx)
