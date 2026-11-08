"""Client assessment routes — registration + permission decorators only (view: member:list, write: member:update)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.assessment_controller import AssessmentController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.assessment import AssessmentInput, AssessmentResponse

router = APIRouter(prefix="/api/v1/assessments", tags=["members"])


@router.get("/member/{member_id}", response_model=ResponseEnvelope[list[AssessmentResponse]],
            dependencies=[Depends(require_permission("member:list"))])
async def list_assessments(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                           controller: AssessmentController = Depends()):
    """Newest first."""
    return await controller.list_for_member(member_id, scope)


@router.post("/member/{member_id}", response_model=ResponseEnvelope[AssessmentResponse], status_code=201,
             dependencies=[Depends(require_permission("member:update"))])
async def create_assessment(member_id: UUID, body: AssessmentInput, scope: BranchScope = Depends(get_branch_scope),
                            ctx: RequestContext = Depends(get_current_user),
                            controller: AssessmentController = Depends()):
    return await controller.create(member_id, body, scope, ctx)


@router.put("/{assessment_id}", response_model=ResponseEnvelope[AssessmentResponse],
            dependencies=[Depends(require_permission("member:update"))])
async def update_assessment(assessment_id: UUID, body: AssessmentInput, scope: BranchScope = Depends(get_branch_scope),
                            ctx: RequestContext = Depends(get_current_user),
                            controller: AssessmentController = Depends()):
    return await controller.update(assessment_id, body, scope, ctx)


@router.delete("/{assessment_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("member:update"))])
async def delete_assessment(assessment_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                            ctx: RequestContext = Depends(get_current_user),
                            controller: AssessmentController = Depends()):
    return await controller.delete(assessment_id, scope, ctx)
