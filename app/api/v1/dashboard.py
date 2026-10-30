"""Dashboard routes — registration + permission decorators only."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from iam_core import require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.dashboard_controller import DashboardController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope
from app.schemas.dashboard import DashboardSummary

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=ResponseEnvelope[DashboardSummary],
            dependencies=[Depends(require_permission("dashboard:view"))])
async def dashboard_summary(scope: BranchScope = Depends(get_branch_scope),
                            controller: DashboardController = Depends()):
    return await controller.summary(scope)
