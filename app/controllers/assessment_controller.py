"""Client assessment request/response handling — no business logic (AssessmentService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.assessment import AssessmentInput, AssessmentResponse
from app.services.assessment_service import AssessmentService


class AssessmentController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = AssessmentService(db)

    async def list_for_member(self, member_id: UUID, scope: BranchScope) -> ResponseEnvelope[list[AssessmentResponse]]:
        return ResponseEnvelope.ok([AssessmentResponse(**a) for a in
                                    await self._service.list_for_member(member_id, scope)])

    async def create(self, member_id: UUID, body: AssessmentInput, scope: BranchScope,
                     ctx: RequestContext) -> ResponseEnvelope[AssessmentResponse]:
        data = await self._service.create(member_id, body, scope, ctx)
        return ResponseEnvelope.ok(AssessmentResponse(**data), message="Assessment saved")

    async def update(self, assessment_id: UUID, body: AssessmentInput, scope: BranchScope,
                     ctx: RequestContext) -> ResponseEnvelope[AssessmentResponse]:
        data = await self._service.update(assessment_id, body, scope, ctx)
        return ResponseEnvelope.ok(AssessmentResponse(**data), message="Assessment updated")

    async def delete(self, assessment_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete(assessment_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Assessment deleted")
