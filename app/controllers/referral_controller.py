"""Referral request/response handling — no business logic (ReferralService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.referral import (EligibleList, GiveIn, GiveOut, ProgramIn, ProgramOut, ReferralCounts,
                                  ReferralStatus, ReferralTree, RewardRow)
from app.services.referral_service import ReferralService


class ReferralController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = ReferralService(db)

    async def status(self, scope: BranchScope) -> ResponseEnvelope[ReferralStatus]:
        return ResponseEnvelope.ok(ReferralStatus(**await self._service.status(scope)))

    async def programs(self, scope: BranchScope) -> ResponseEnvelope[list[ProgramOut]]:
        return ResponseEnvelope.ok([ProgramOut(**p) for p in await self._service.programs(scope)])

    async def set_program(self, body: ProgramIn, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[ProgramOut]:
        data = await self._service.set_program(body, scope, ctx)
        return ResponseEnvelope.ok(ProgramOut(**data), message=f"Referral reward saved for {data['month_label']}")

    async def eligible(self, scope: BranchScope) -> ResponseEnvelope[EligibleList]:
        return ResponseEnvelope.ok(EligibleList(**await self._service.eligible(scope)))

    async def rewards(self, scope: BranchScope, pagination: PaginationParams, status: str,
                      search: str | None) -> PaginatedEnvelope[RewardRow]:
        rows, total = await self._service.rewards(scope, status, search, offset=pagination.offset,
                                                  limit=pagination.limit)
        return PaginatedEnvelope.ok([RewardRow(**r) for r in rows], total, pagination.page, pagination.page_size)

    async def counts(self, scope: BranchScope) -> ResponseEnvelope[ReferralCounts]:
        return ResponseEnvelope.ok(ReferralCounts(**await self._service.counts(scope)))

    async def give(self, body: GiveIn, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[GiveOut]:
        data = await self._service.give(body, scope, ctx)
        return ResponseEnvelope.ok(GiveOut(**data),
                                   message=f"{data['reward']} given to {data['name']} ({data['month_label']})")

    async def tree(self, member_id: UUID, scope: BranchScope, levels: int = 1) -> ResponseEnvelope[ReferralTree]:
        return ResponseEnvelope.ok(ReferralTree(**await self._service.tree(member_id, scope, levels)))
