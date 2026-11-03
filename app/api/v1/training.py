"""Personal training routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.training_controller import TrainingController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.common import SortDir
from app.schemas.training import (PTCounts, PTSessionLogCreate, PTSessionLogResponse, PTSubscribeRequest,
                                  PTSubscriptionResponse, PTTrainerUpdate)

router = APIRouter(prefix="/api/v1/personal-training", tags=["personal-training"])


@router.get("", response_model=PaginatedEnvelope[PTSubscriptionResponse],
            dependencies=[Depends(require_permission("pt:list"))])
async def list_pt(
    pagination: PaginationParams = Depends(get_pagination),
    status: Literal["ACTIVE", "COMPLETED", "EXPIRED", "ALL"] = Query(default="ACTIVE"),
    paid_only: bool = Query(default=True),
    search: str | None = Query(default=None, max_length=100),
    trainer_id: UUID | None = Query(default=None),
    member_id: UUID | None = Query(default=None),
    sort_by: Literal["member_name", "trainer_name", "start_date", "expiry_date", "sessions_remaining",
                     "created_at"] | None = Query(default=None),
    sort_dir: SortDir = Query(default="desc"),
    scope: BranchScope = Depends(get_branch_scope),
    controller: TrainingController = Depends(),
):
    return await controller.list_pt(scope, pagination, status, paid_only, search, trainer_id, member_id,
                                    sort_by, sort_dir)


@router.get("/counts", response_model=ResponseEnvelope[PTCounts],
            dependencies=[Depends(require_permission("pt:list"))])
async def pt_counts(paid_only: bool = Query(default=True), scope: BranchScope = Depends(get_branch_scope),
                    controller: TrainingController = Depends()):
    return await controller.counts(scope, paid_only)


@router.post("/subscribe", response_model=ResponseEnvelope[PTSubscriptionResponse], status_code=201,
             dependencies=[Depends(require_permission("pt:create"))])
async def subscribe(body: PTSubscribeRequest, scope: BranchScope = Depends(get_branch_scope),
                    ctx: RequestContext = Depends(get_current_user), controller: TrainingController = Depends()):
    return await controller.subscribe(body, scope, ctx)


@router.get("/{pt_id}", response_model=ResponseEnvelope[PTSubscriptionResponse],
            dependencies=[Depends(require_permission("pt:list"))])
async def get_pt(pt_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                 controller: TrainingController = Depends()):
    return await controller.get_pt(pt_id, scope)


@router.post("/{pt_id}/trainer", response_model=ResponseEnvelope[PTSubscriptionResponse],
             dependencies=[Depends(require_permission("pt:update"))])
async def change_trainer(pt_id: UUID, body: PTTrainerUpdate, scope: BranchScope = Depends(get_branch_scope),
                         ctx: RequestContext = Depends(get_current_user), controller: TrainingController = Depends()):
    return await controller.change_trainer(pt_id, body, scope, ctx)


@router.post("/{pt_id}/sessions", response_model=ResponseEnvelope[PTSubscriptionResponse], status_code=201,
             dependencies=[Depends(require_permission("pt:log"))])
async def log_session(pt_id: UUID, body: PTSessionLogCreate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: TrainingController = Depends()):
    return await controller.log_session(pt_id, body, scope, ctx)


@router.get("/{pt_id}/sessions", response_model=ResponseEnvelope[list[PTSessionLogResponse]],
            dependencies=[Depends(require_permission("pt:list"))])
async def session_history(pt_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                          controller: TrainingController = Depends()):
    return await controller.sessions(pt_id, scope)
