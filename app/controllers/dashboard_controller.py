"""Dashboard request/response handling — no business logic (DashboardService)."""
from __future__ import annotations

from fastapi import Depends
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.dashboard import DashboardSummary
from app.services.dashboard_service import DashboardService


class DashboardController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = DashboardService(db)

    async def summary(self, scope: BranchScope) -> ResponseEnvelope[DashboardSummary]:
        return ResponseEnvelope.ok(DashboardSummary(**await self._service.summary(scope)))
