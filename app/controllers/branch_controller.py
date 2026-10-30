"""Branches request/response handling — no business logic (BranchService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.organization import BranchCreate, BranchPasswordReset, BranchResponse, BranchUpdate
from app.services.branch_service import BranchService


class BranchController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = BranchService(db)

    async def list_branches(self, ctx: RequestContext, pagination: PaginationParams,
                            search: str | None) -> PaginatedEnvelope[BranchResponse]:
        rows, total = await self._service.list_branches(ctx, offset=pagination.offset, limit=pagination.limit,
                                                        search=search)
        return PaginatedEnvelope.ok([BranchResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def get_branch(self, branch_id: UUID, ctx: RequestContext) -> ResponseEnvelope[BranchResponse]:
        return ResponseEnvelope.ok(BranchResponse(**await self._service.get_branch(branch_id, ctx)))

    async def create_branch(self, body: BranchCreate, ctx: RequestContext) -> ResponseEnvelope[BranchResponse]:
        data = await self._service.create_branch(body, ctx)
        return ResponseEnvelope.ok(BranchResponse(**data), message="Branch created")

    async def update_branch(self, branch_id: UUID, body: BranchUpdate,
                            ctx: RequestContext) -> ResponseEnvelope[BranchResponse]:
        data = await self._service.update_branch(branch_id, body, ctx)
        return ResponseEnvelope.ok(BranchResponse(**data), message="Branch updated")

    async def delete_branch(self, branch_id: UUID, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete_branch(branch_id, ctx)
        return ResponseEnvelope.ok(None, message="Branch deleted")

    async def reset_login_password(self, branch_id: UUID, body: BranchPasswordReset,
                                   ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.reset_login_password(branch_id, body.new_password, ctx)
        return ResponseEnvelope.ok(None, message="Branch login password reset")
