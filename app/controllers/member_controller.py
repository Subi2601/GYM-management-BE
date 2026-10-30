"""Members request/response handling — no business logic (MemberService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.common import CodeResponse
from app.schemas.member import MemberCounts, MemberCreate, MemberResponse, MemberUpdate
from app.services.member_service import MemberService


class MemberController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = MemberService(db)

    async def list_members(self, scope: BranchScope, pagination: PaginationParams, search: str | None,
                           state_filter: str | None, plan_id: UUID | None,
                           show_pii: bool) -> PaginatedEnvelope[MemberResponse]:
        rows, total = await self._service.list_members(
            scope, offset=pagination.offset, limit=pagination.limit, search=search,
            state_filter=state_filter, plan_id=plan_id, show_pii=show_pii)
        return PaginatedEnvelope.ok([MemberResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def get_member(self, member_id: UUID, scope: BranchScope,
                         show_pii: bool) -> ResponseEnvelope[MemberResponse]:
        return ResponseEnvelope.ok(MemberResponse(**await self._service.get_member(member_id, scope, show_pii)))

    async def next_registration_id(self, scope: BranchScope) -> ResponseEnvelope[CodeResponse]:
        return ResponseEnvelope.ok(CodeResponse(code=await self._service.next_registration_id(scope)))

    async def counts(self, scope: BranchScope) -> ResponseEnvelope[MemberCounts]:
        return ResponseEnvelope.ok(MemberCounts(**await self._service.counts(scope)))

    async def create_member(self, body: MemberCreate, scope: BranchScope, ctx: RequestContext,
                            show_pii: bool) -> ResponseEnvelope[MemberResponse]:
        data = await self._service.create_member(body, scope, ctx, show_pii)
        return ResponseEnvelope.ok(MemberResponse(**data), message="Member registered")

    async def update_member(self, member_id: UUID, body: MemberUpdate, scope: BranchScope,
                            ctx: RequestContext, show_pii: bool) -> ResponseEnvelope[MemberResponse]:
        data = await self._service.update_member(member_id, body, scope, ctx, show_pii)
        return ResponseEnvelope.ok(MemberResponse(**data), message="Member updated")

    async def delete_member(self, member_id: UUID, scope: BranchScope,
                            ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete_member(member_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Member deleted")
