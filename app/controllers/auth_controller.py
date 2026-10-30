"""Auth request/response handling — cookies + envelopes. No business logic (AuthService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request, Response
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import REFRESH_COOKIE_NAME, REFRESH_COOKIE_PATH, REFRESH_TTL_SECONDS
from app.dependencies import get_db
from app.schemas.auth import ChangePasswordRequest, LoginRequest, MeResponse, TokenResponse
from app.services.auth_service import ACCESS_TTL_SECONDS, AuthService


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(REFRESH_COOKIE_NAME, token, max_age=REFRESH_TTL_SECONDS, httponly=True,
                        secure=settings.COOKIE_SECURE, samesite="lax", path=REFRESH_COOKIE_PATH)


class AuthController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = AuthService(db)

    async def login(self, body: LoginRequest, request: Request,
                    response: Response) -> ResponseEnvelope[TokenResponse]:
        access, refresh = await self._service.login(body.email, body.password, client_ip(request),
                                                    request.headers.get("User-Agent"))
        _set_refresh_cookie(response, refresh)
        return ResponseEnvelope.ok(TokenResponse(access_token=access, expires_in=ACCESS_TTL_SECONDS),
                                   message="Signed in")

    async def refresh(self, request: Request, response: Response) -> ResponseEnvelope[TokenResponse]:
        access, refresh = await self._service.refresh(request.cookies.get(REFRESH_COOKIE_NAME))
        _set_refresh_cookie(response, refresh)
        return ResponseEnvelope.ok(TokenResponse(access_token=access, expires_in=ACCESS_TTL_SECONDS))

    async def logout(self, session_id: UUID, response: Response) -> ResponseEnvelope[None]:
        await self._service.logout(session_id)
        response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
        return ResponseEnvelope.ok(None, message="Signed out")

    async def me(self, user_id: UUID) -> ResponseEnvelope[MeResponse]:
        return ResponseEnvelope.ok(MeResponse(**await self._service.me(user_id)))

    async def change_password(self, user_id: UUID, body: ChangePasswordRequest) -> ResponseEnvelope[None]:
        await self._service.change_password(user_id, body.current_password, body.new_password)
        return ResponseEnvelope.ok(None, message="Password changed")
