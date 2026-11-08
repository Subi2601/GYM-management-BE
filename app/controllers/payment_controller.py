"""Payments request/response handling — no business logic (PaymentService)."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PaymentMode
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.payment import InvoiceResponse, PaymentCreate, PaymentResponse, PaymentStats
from app.services.payment_service import PaymentService


class PaymentController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = PaymentService(db)

    async def list_payments(self, scope: BranchScope, pagination: PaginationParams, search: str | None,
                            payment_mode: PaymentMode | None, date_from: date | None,
                            date_to: date | None, has_balance: bool | None, sort_by: str | None,
                            sort_dir: str) -> PaginatedEnvelope[PaymentResponse]:
        rows, total = await self._service.list_payments(
            scope, offset=pagination.offset, limit=pagination.limit, search=search, payment_mode=payment_mode,
            date_from=date_from, date_to=date_to, has_balance=has_balance, sort_by=sort_by, sort_dir=sort_dir)
        return PaginatedEnvelope.ok([PaymentResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def stats(self, scope: BranchScope) -> ResponseEnvelope[PaymentStats]:
        return ResponseEnvelope.ok(PaymentStats(**await self._service.stats(scope)))

    async def invoice(self, payment_id: UUID, scope: BranchScope) -> ResponseEnvelope[InvoiceResponse]:
        return ResponseEnvelope.ok(InvoiceResponse(**await self._service.invoice(payment_id, scope)))

    async def public_invoice(self, token: str) -> ResponseEnvelope[InvoiceResponse]:
        return ResponseEnvelope.ok(InvoiceResponse(**await self._service.public_invoice(token)))

    async def create_payment(self, body: PaymentCreate, scope: BranchScope,
                             ctx: RequestContext) -> ResponseEnvelope[PaymentResponse]:
        data = await self._service.create_payment(body, scope, ctx)
        return ResponseEnvelope.ok(PaymentResponse(**data), message="Payment recorded")
