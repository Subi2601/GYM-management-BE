"""Gym settings request/response handling — no business logic (SettingsService)."""
from __future__ import annotations

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.settings import DeskSettings, GymSettingsResponse, GymSettingsUpdate
from app.services.settings_service import SettingsService


class SettingsController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = SettingsService(db)

    async def get(self, scope: BranchScope) -> ResponseEnvelope[GymSettingsResponse]:
        return ResponseEnvelope.ok(GymSettingsResponse(**await self._service.get(scope.organization_id)))

    async def update(self, body: GymSettingsUpdate, scope: BranchScope,
                     ctx: RequestContext) -> ResponseEnvelope[GymSettingsResponse]:
        data = await self._service.update(scope.organization_id, body, ctx)
        return ResponseEnvelope.ok(GymSettingsResponse(**data), message="Configuration saved")

    async def desk(self, scope: BranchScope) -> ResponseEnvelope[DeskSettings]:
        return ResponseEnvelope.ok(DeskSettings(**await self._service.get(scope.organization_id)))
