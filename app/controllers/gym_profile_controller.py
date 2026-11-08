"""Gym profile request/response handling — no business logic (GymProfileService)."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Depends, Response
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.gym_profile import GymFileUpload, GymProfile, GymProfileUpdate
from app.services.gym_profile_service import GymProfileService


class GymProfileController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = GymProfileService(db)

    async def get(self, ctx: RequestContext) -> ResponseEnvelope[GymProfile]:
        return ResponseEnvelope.ok(GymProfile(**await self._service.profile(ctx.organization_id)))

    async def update(self, body: GymProfileUpdate, ctx: RequestContext) -> ResponseEnvelope[GymProfile]:
        data = await self._service.update(ctx.organization_id, body, ctx)
        return ResponseEnvelope.ok(GymProfile(**data), message="Gym profile saved")

    async def upload(self, kind: str, body: GymFileUpload, ctx: RequestContext) -> ResponseEnvelope[GymProfile]:
        data = await self._service.upload(ctx.organization_id, kind, body, ctx)
        return ResponseEnvelope.ok(GymProfile(**data),
                                   message="Logo updated" if kind == "LOGO" else "Terms & conditions uploaded")

    async def remove(self, kind: str, ctx: RequestContext) -> ResponseEnvelope[GymProfile]:
        data = await self._service.remove(ctx.organization_id, kind)
        return ResponseEnvelope.ok(GymProfile(**data),
                                   message="Logo removed" if kind == "LOGO" else "Terms & conditions removed")

    async def public_file(self, code: str, kind: str) -> Response:
        f = await self._service.public_file(code, kind)
        return Response(content=f.data, media_type=f.content_type, headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(f.file_name)}",
            "Cache-Control": "public, max-age=300"})
