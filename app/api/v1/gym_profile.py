"""Gym profile routes (Gym Settings page) — registration + permission decorators only.

Read: any signed-in account of the gym. Change: `gym:manage`. Logo / terms are also served publicly by gym code
(AuthMiddleware skips /api/v1/public/) because members open them from invoices and WhatsApp.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.gym_profile_controller import GymProfileController
from app.dependencies import get_current_user
from app.schemas.gym_profile import GymFileUpload, GymProfile, GymProfileUpdate

router = APIRouter(prefix="/api/v1/gym-profile", tags=["gym profile"])
_MANAGE = [Depends(require_permission("gym:manage"))]
_KIND = {"logo": "LOGO", "terms": "TERMS"}


@router.get("", response_model=ResponseEnvelope[GymProfile], dependencies=[Depends(require_permission("auth:me"))])
async def get_profile(ctx: RequestContext = Depends(get_current_user), controller: GymProfileController = Depends()):
    return await controller.get(ctx)


@router.put("", response_model=ResponseEnvelope[GymProfile], dependencies=_MANAGE)
async def update_profile(body: GymProfileUpdate, ctx: RequestContext = Depends(get_current_user),
                         controller: GymProfileController = Depends()):
    return await controller.update(body, ctx)


@router.put("/{kind}", response_model=ResponseEnvelope[GymProfile], dependencies=_MANAGE)
async def upload_file(kind: Literal["logo", "terms"], body: GymFileUpload,
                      ctx: RequestContext = Depends(get_current_user), controller: GymProfileController = Depends()):
    """Logo (PNG / JPG / WEBP ≤ 1 MB) or terms & conditions (PDF ≤ 5 MB); replaces the current one."""
    return await controller.upload(_KIND[kind], body, ctx)


@router.delete("/{kind}", response_model=ResponseEnvelope[GymProfile], dependencies=_MANAGE)
async def remove_file(kind: Literal["logo", "terms"], ctx: RequestContext = Depends(get_current_user),
                      controller: GymProfileController = Depends()):
    return await controller.remove(_KIND[kind], ctx)


public_router = APIRouter(prefix="/api/v1/public/gyms", tags=["public gym files"])
_CODE = Path(pattern=r"^[A-Za-z0-9_-]{2,40}$")


@public_router.get("/{code}/logo")
async def public_logo(code: str = _CODE, controller: GymProfileController = Depends()):
    return await controller.public_file(code, "LOGO")


@public_router.get("/{code}/terms")
async def public_terms(code: str = _CODE, controller: GymProfileController = Depends()):
    return await controller.public_file(code, "TERMS")
