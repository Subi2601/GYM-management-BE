"""Resolves the per-request BranchScope (SaaS data boundary)."""
from __future__ import annotations

from uuid import UUID

from iam_core import RequestContext
from iam_core.exceptions import AuthenticationError, PermissionDeniedError
from rbac.engine import RBACEngine
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import SWITCH_BRANCH_PERMISSION

PII_VIEW_PERMISSION = "pii:view"
PAYROLL_VIEW_PERMISSION = "salary:list"


class ScopeService:
    def __init__(self, db: AsyncSession) -> None:
        self._users = UserRepository(db)
        self._orgs = OrganizationRepository(db)
        self._rbac = RBACEngine(db)

    async def resolve(self, ctx: RequestContext, requested_branch: str | None) -> BranchScope:
        if ctx.organization_id is None:
            raise PermissionDeniedError("This account is not attached to a gym organization")
        user = await self._users.get_user(ctx.user_id)
        if user is None:
            raise AuthenticationError()
        org_branch_ids = await self._orgs.list_branch_ids(ctx.organization_id)
        can_switch = ctx.is_superadmin or await self._rbac.has_permission(ctx.user_id, SWITCH_BRANCH_PERMISSION)

        if requested_branch:
            try:
                branch_id = UUID(requested_branch)
            except ValueError:
                raise PermissionDeniedError("Invalid branch")
            if branch_id not in org_branch_ids:
                raise PermissionDeniedError("Branch does not belong to your organization")
            if not can_switch and branch_id != user.branch_id:
                raise PermissionDeniedError("You can only access your assigned branch")
            return BranchScope(ctx.organization_id, branch_id, (branch_id,))

        if can_switch:
            # "All Branches" — read across the organization, writes need a branch.
            return BranchScope(ctx.organization_id, None, tuple(org_branch_ids))
        if user.branch_id is None:
            raise PermissionDeniedError("No branch is assigned to this account")
        return BranchScope(ctx.organization_id, user.branch_id, (user.branch_id,))

    async def can_view_pii(self, ctx: RequestContext) -> bool:
        return ctx.is_superadmin or await self._rbac.has_permission(ctx.user_id, PII_VIEW_PERMISSION)

    async def can_view_payroll(self, ctx: RequestContext) -> bool:
        return ctx.is_superadmin or await self._rbac.has_permission(ctx.user_id, PAYROLL_VIEW_PERMISSION)
