"""Roles & access controller — builds schemas and envelopes."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.role import (CatalogModule, RoleCreate, RoleDetail, RolePermissionsUpdate, RoleResponse,
                              RoleUpdate)
from app.services.role_service import RoleService


class RoleController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = RoleService(db)

    async def list_roles(self, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[list[RoleResponse]]:
        return ResponseEnvelope.ok([RoleResponse(**r) for r in await self._service.list_roles(scope, ctx)])

    async def assignable(self, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[list[RoleResponse]]:
        return ResponseEnvelope.ok([RoleResponse(**r) for r in await self._service.assignable(scope, ctx)])

    async def catalog(self) -> ResponseEnvelope[list[CatalogModule]]:
        return ResponseEnvelope.ok([CatalogModule(**m) for m in await self._service.catalog()])

    async def get_role(self, role_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[RoleDetail]:
        return ResponseEnvelope.ok(RoleDetail(**await self._service.get_role(role_id, scope, ctx)))

    async def create_role(self, body: RoleCreate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[RoleDetail]:
        data = await self._service.create_role(body, scope, ctx)
        return ResponseEnvelope.ok(RoleDetail(**data), message=f"Role {data['name']} created")

    async def update_role(self, role_id: UUID, body: RoleUpdate, scope: BranchScope,
                          ctx: RequestContext) -> ResponseEnvelope[RoleDetail]:
        data = await self._service.update_role(role_id, body, scope, ctx)
        return ResponseEnvelope.ok(RoleDetail(**data), message=f"Role {data['name']} updated")

    async def set_permissions(self, role_id: UUID, body: RolePermissionsUpdate, scope: BranchScope,
                              ctx: RequestContext) -> ResponseEnvelope[RoleDetail]:
        data = await self._service.set_permissions(role_id, body.codes, scope, ctx)
        return ResponseEnvelope.ok(RoleDetail(**data),
                                   message=f"Access saved for {data['name']}. Logins get it when they next sign in")

    async def delete_role(self, role_id: UUID, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.delete_role(role_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Role deleted")
