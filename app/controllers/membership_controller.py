"""Membership actions request/response handling — no business logic (MembershipService)."""
from __future__ import annotations

from datetime import date
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, Response
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.membership import ActionResult, DocumentOut, MembershipActions, RefundOut
from app.services.membership_service import MembershipService


class MembershipController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = MembershipService(db)

    @staticmethod
    def _result(data: dict) -> ResponseEnvelope[ActionResult]:
        message = data.pop("message", None)
        return ResponseEnvelope.ok(ActionResult(**data), message=message)

    async def actions(self, member_id: UUID, scope: BranchScope) -> ResponseEnvelope[MembershipActions]:
        return ResponseEnvelope.ok(MembershipActions(**await self._service.actions(member_id, scope)))

    async def set_allowance(self, subscription_id: UUID, body, scope: BranchScope,
                            ctx: RequestContext) -> ResponseEnvelope[MembershipActions]:
        data = await self._service.set_allowance(subscription_id, body, scope, ctx)
        return ResponseEnvelope.ok(MembershipActions(**data), message="Freeze allowance saved")

    async def freeze(self, subscription_id: UUID, body, scope: BranchScope,
                     ctx: RequestContext) -> ResponseEnvelope[ActionResult]:
        return self._result(await self._service.freeze(subscription_id, body, scope, ctx))

    async def resume(self, freeze_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[ActionResult]:
        return self._result(await self._service.resume(freeze_id, scope, ctx))

    async def transfer(self, subscription_id: UUID, body, scope: BranchScope,
                       ctx: RequestContext) -> ResponseEnvelope[ActionResult]:
        return self._result(await self._service.transfer(subscription_id, body, scope, ctx))

    async def cancel(self, subscription_id: UUID, body, scope: BranchScope, ctx: RequestContext,
                     show_pii: bool) -> ResponseEnvelope[ActionResult]:
        return self._result(await self._service.cancel(subscription_id, body, scope, ctx, show_pii))

    async def documents(self, member_id: UUID, scope: BranchScope) -> ResponseEnvelope[list[DocumentOut]]:
        return ResponseEnvelope.ok([DocumentOut(**d) for d in await self._service.member_documents(member_id, scope)])

    async def download(self, document_id: UUID, scope: BranchScope) -> Response:
        doc = await self._service.document(document_id, scope)
        return Response(content=doc.data, media_type=doc.content_type, headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(doc.file_name)}",
            "Cache-Control": "private, no-store"})

    async def list_refunds(self, scope: BranchScope, pagination: PaginationParams, search: str | None,
                           date_from: date | None, date_to: date | None,
                           show_pii: bool) -> PaginatedEnvelope[RefundOut]:
        rows, total = await self._service.list_refunds(scope, offset=pagination.offset, limit=pagination.limit,
                                                       search=search, date_from=date_from, date_to=date_to,
                                                       show_pii=show_pii)
        return PaginatedEnvelope.ok([RefundOut(**r) for r in rows], total, pagination.page, pagination.page_size)
