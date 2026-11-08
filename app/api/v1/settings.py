"""Gym settings routes — registration + permission decorators only."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.settings_controller import SettingsController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.settings import DeskSettings, GymSettingsResponse, GymSettingsUpdate

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=ResponseEnvelope[GymSettingsResponse],
            dependencies=[Depends(require_permission("setting:manage"))])
async def get_settings(scope: BranchScope = Depends(get_branch_scope), controller: SettingsController = Depends()):
    return await controller.get(scope)


@router.put("", response_model=ResponseEnvelope[GymSettingsResponse],
            dependencies=[Depends(require_permission("setting:manage"))])
async def update_settings(body: GymSettingsUpdate, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          controller: SettingsController = Depends()):
    """Gym-wide: applies to every branch."""
    return await controller.update(body, scope, ctx)


@router.get("/desk", response_model=ResponseEnvelope[DeskSettings],
            dependencies=[Depends(require_permission("auth:me"))])
async def desk_settings(scope: BranchScope = Depends(get_branch_scope), controller: SettingsController = Depends()):
    """Read-only values the desk screens show: the trial offer (Leads) and the renewal window (Renewals)."""
    return await controller.desk(scope)
