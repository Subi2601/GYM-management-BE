"""Auth routes — registration + permission decorators only, logic in controller/service."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.auth_controller import AuthController
from app.dependencies import get_current_user
from app.schemas.auth import ChangePasswordRequest, LoginRequest, MeResponse, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=ResponseEnvelope[TokenResponse])
async def login(body: LoginRequest, request: Request, response: Response,
                controller: AuthController = Depends()):
    return await controller.login(body, request, response)


@router.post("/refresh", response_model=ResponseEnvelope[TokenResponse])
async def refresh(request: Request, response: Response, controller: AuthController = Depends()):
    return await controller.refresh(request, response)


@router.post("/logout", response_model=ResponseEnvelope[None])
async def logout(response: Response, ctx: RequestContext = Depends(get_current_user),
                 controller: AuthController = Depends()):
    return await controller.logout(ctx.session_id, response)


@router.get("/me", response_model=ResponseEnvelope[MeResponse],
            dependencies=[Depends(require_permission("auth:me"))])
async def me(ctx: RequestContext = Depends(get_current_user), controller: AuthController = Depends()):
    return await controller.me(ctx.user_id)


@router.post("/change-password", response_model=ResponseEnvelope[None],
             dependencies=[Depends(require_permission("auth:me"))])
async def change_password(body: ChangePasswordRequest, ctx: RequestContext = Depends(get_current_user),
                          controller: AuthController = Depends()):
    return await controller.change_password(ctx.user_id, body)
