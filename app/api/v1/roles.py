"""Roles & access routes — registration + permission decorators only."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.role_controller import RoleController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.role import (CatalogModule, RoleCreate, RoleDetail, RolePermissionsUpdate, RoleResponse,
                              RoleUpdate)

router = APIRouter(prefix="/api/v1/roles", tags=["roles"])


@router.get("", response_model=ResponseEnvelope[list[RoleResponse]],
            dependencies=[Depends(require_permission("role:list"))])
async def list_roles(scope: BranchScope = Depends(get_branch_scope), ctx: RequestContext = Depends(get_current_user),
                     controller: RoleController = Depends()):
    """The gym's roles, highest level first, with how many logins use each."""
    return await controller.list_roles(scope, ctx)


@router.get("/catalog", response_model=ResponseEnvelope[list[CatalogModule]],
            dependencies=[Depends(require_permission("role:list"))])
async def role_catalog(controller: RoleController = Depends()):
    """Module → screen → permission tree for the access matrix."""
    return await controller.catalog()


@router.get("/assignable", response_model=ResponseEnvelope[list[RoleResponse]],
            dependencies=[Depends(require_permission("employee:login"))])
async def assignable_roles(scope: BranchScope = Depends(get_branch_scope),
                           ctx: RequestContext = Depends(get_current_user), controller: RoleController = Depends()):
    """Roles the caller may give a staff login (below their own level)."""
    return await controller.assignable(scope, ctx)


@router.get("/{role_id}", response_model=ResponseEnvelope[RoleDetail],
            dependencies=[Depends(require_permission("role:list"))])
async def get_role(role_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                   ctx: RequestContext = Depends(get_current_user), controller: RoleController = Depends()):
    return await controller.get_role(role_id, scope, ctx)


@router.post("", response_model=ResponseEnvelope[RoleDetail], status_code=201,
             dependencies=[Depends(require_permission("role:manage"))])
async def create_role(body: RoleCreate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: RoleController = Depends()):
    return await controller.create_role(body, scope, ctx)


@router.put("/{role_id}", response_model=ResponseEnvelope[RoleDetail],
            dependencies=[Depends(require_permission("role:manage"))])
async def update_role(role_id: UUID, body: RoleUpdate, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: RoleController = Depends()):
    return await controller.update_role(role_id, body, scope, ctx)


@router.put("/{role_id}/permissions", response_model=ResponseEnvelope[RoleDetail],
            dependencies=[Depends(require_permission("role:manage"))])
async def set_role_permissions(role_id: UUID, body: RolePermissionsUpdate,
                               scope: BranchScope = Depends(get_branch_scope),
                               ctx: RequestContext = Depends(get_current_user),
                               controller: RoleController = Depends()):
    """Replace the role's access with exactly these permission codes."""
    return await controller.set_permissions(role_id, body, scope, ctx)


@router.delete("/{role_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("role:manage"))])
async def delete_role(role_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: RoleController = Depends()):
    return await controller.delete_role(role_id, scope, ctx)
