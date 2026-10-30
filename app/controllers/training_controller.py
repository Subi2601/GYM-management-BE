"""Personal training request/response handling — no business logic (TrainingService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PTStatus
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.training import (PTSessionLogCreate, PTSessionLogResponse, PTSubscribeRequest,
                                  PTSubscriptionResponse, PTTrainerUpdate)
from app.services.training_service import TrainingService


class TrainingController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = TrainingService(db)

    async def list_pt(self, scope: BranchScope, pagination: PaginationParams, status: str,
                      paid_only: bool, search: str | None, trainer_id: UUID | None,
                      member_id: UUID | None) -> PaginatedEnvelope[PTSubscriptionResponse]:
        rows, total = await self._service.list_pt(
            scope, offset=pagination.offset, limit=pagination.limit,
            status=None if status == "ALL" else PTStatus(status), paid_only=paid_only,
            search=search, trainer_id=trainer_id, member_id=member_id)
        return PaginatedEnvelope.ok([PTSubscriptionResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def get_pt(self, pt_id: UUID, scope: BranchScope) -> ResponseEnvelope[PTSubscriptionResponse]:
        return ResponseEnvelope.ok(PTSubscriptionResponse(**await self._service.get_pt(pt_id, scope)))

    async def sessions(self, pt_id: UUID, scope: BranchScope) -> ResponseEnvelope[list[PTSessionLogResponse]]:
        rows = await self._service.sessions(pt_id, scope)
        return ResponseEnvelope.ok([PTSessionLogResponse(**r) for r in rows])

    async def subscribe(self, body: PTSubscribeRequest, scope: BranchScope,
                        ctx: RequestContext) -> ResponseEnvelope[PTSubscriptionResponse]:
        data = await self._service.subscribe(body, scope, ctx)
        return ResponseEnvelope.ok(PTSubscriptionResponse(**data), message="Member subscribed to personal training")

    async def change_trainer(self, pt_id: UUID, body: PTTrainerUpdate, scope: BranchScope,
                             ctx: RequestContext) -> ResponseEnvelope[PTSubscriptionResponse]:
        data = await self._service.change_trainer(pt_id, body, scope, ctx)
        return ResponseEnvelope.ok(PTSubscriptionResponse(**data), message="Trainer updated")

    async def log_session(self, pt_id: UUID, body: PTSessionLogCreate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[PTSubscriptionResponse]:
        data = await self._service.log_session(pt_id, body, scope, ctx)
        return ResponseEnvelope.ok(PTSubscriptionResponse(**data), message="Session logged")
