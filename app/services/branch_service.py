"""Branches business logic — branch + OWNER login provisioning, rename, soft delete, login password reset.

Branch endpoints manage the scope itself, so they work on ctx.organization_id instead of a BranchScope.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from iam_core import RequestContext
from iam_core.exceptions import PermissionDeniedError
from rbac.models import UserRole
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountRole
from app.services.role_service import RoleService
from app.utils.rbac_catalog import OWNER_ROLE
from app.core.security import hash_password
from app.models.organization import Branch
from app.models.user import User
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository

MAX_USERS_PER_BRANCH = 5   # carried over from the old AuthService.createUser


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_org(ctx: RequestContext) -> UUID:
    if ctx.organization_id is None:
        raise PermissionDeniedError("This account is not attached to a gym organization")
    return ctx.organization_id


class BranchService:
    def __init__(self, db: AsyncSession) -> None:
        self._orgs = OrganizationRepository(db)
        self._users = UserRepository(db)
        self._roles = RoleService(db)

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def branch_out(b: Branch, login_email: str | None, counts: tuple[int, int] = (0, 0)) -> dict:
        return {"id": b.id, "organization_id": b.organization_id, "branch_name": b.branch_name,
                "location": b.location, "login_email": login_email, "phone": b.phone, "email": b.email,
                "gstin": b.gstin, "is_head_office": b.is_head_office,
                "members_count": counts[0], "staff_count": counts[1],
                "created_at": b.created_at, "updated_at": b.updated_at}

    async def _contacts(self, branch: Branch, data, actor_id) -> None:
        """Phone / email / GSTIN (free text, not unique) and the head office flag (one per gym)."""
        sent = data.model_fields_set
        for field in ("phone", "email", "gstin"):
            if field in sent:
                value = getattr(data, field)
                setattr(branch, field, (value.strip() if isinstance(value, str) else value) or None)
        if "is_head_office" in sent and data.is_head_office is not None:
            if data.is_head_office:
                await self._orgs.clear_head_office(branch.organization_id, branch.id)
            branch.is_head_office = data.is_head_office

    # ── shared provisioning (also used by organization onboarding) ───────
    async def ensure_login_email_free(self, email: str) -> None:
        if await self._users.email_taken(email):
            raise ConflictError("This email is already used by another login")

    async def create_owner_login(self, *, organization_id: UUID, branch_id: UUID, name: str, email: str,
                                 password: str, actor_id: UUID) -> User:
        """OWNER account homed in the branch + its RBAC role link. Caller commits."""
        if await self._users.count_branch_users(branch_id) >= MAX_USERS_PER_BRANCH:
            raise BadRequestError(f"User limit reached for this branch (max {MAX_USERS_PER_BRANCH} users)")
        await self.ensure_login_email_free(email)
        # A new gym gets its Owner / Sub-admin / Manager / Staff roles here (no-op when they exist).
        role = (await self._roles.ensure_org_roles(organization_id, actor_id))[OWNER_ROLE]
        user = await self._users.add(User(
            organization_id=organization_id, branch_id=branch_id, name=name, email=email.lower(),
            password_hash=hash_password(password), role=AccountRole.OWNER, created_by=actor_id))
        await self._users.add_user_role(UserRole(user_id=user.id, role_id=role.id, assigned_by=actor_id))
        return user

    # ── queries ──────────────────────────────────────────────────────────
    async def list_branches(self, ctx: RequestContext, *, offset: int, limit: int,
                            search: str | None) -> tuple[list[dict], int]:
        org_id = _require_org(ctx)
        branches, total = await self._orgs.page_branches(org_id, offset=offset, limit=limit, search=search)
        ids = [b.id for b in branches]
        emails, counts = await self._orgs.branch_owner_emails(ids), await self._orgs.branch_counts(ids)
        return [self.branch_out(b, emails.get(b.id), counts.get(b.id, (0, 0))) for b in branches], total

    async def get_branch(self, branch_id: UUID, ctx: RequestContext) -> dict:
        branch = await self._get(branch_id, ctx)
        login = await self._orgs.branch_owner_login(branch.id)
        counts = (await self._orgs.branch_counts([branch.id])).get(branch.id, (0, 0))
        return self.branch_out(branch, login.email if login else None, counts)

    async def _get(self, branch_id: UUID, ctx: RequestContext) -> Branch:
        branch = await self._orgs.get_branch(_require_org(ctx), branch_id)
        if branch is None:
            raise NotFoundError("Branch")
        return branch

    # ── commands ─────────────────────────────────────────────────────────
    async def create_branch(self, data, ctx: RequestContext) -> dict:
        org_id = _require_org(ctx)
        if await self._orgs.branch_name_taken(org_id, data.branch_name):
            raise ConflictError("A branch with this name already exists")
        await self.ensure_login_email_free(data.login_email)
        branch = await self._orgs.add(Branch(organization_id=org_id, branch_name=data.branch_name,
                                             location=data.location, created_by=ctx.user_id))
        await self._contacts(branch, data, ctx.user_id)
        await self.create_owner_login(organization_id=org_id, branch_id=branch.id,
                                      name=f"{data.branch_name} Admin", email=data.login_email,
                                      password=data.login_password, actor_id=ctx.user_id)
        await self._orgs.commit()
        return await self.get_branch(branch.id, ctx)

    async def update_branch(self, branch_id: UUID, data, ctx: RequestContext) -> dict:
        branch = await self._get(branch_id, ctx)
        sent = data.model_fields_set
        if "branch_name" in sent and data.branch_name and data.branch_name != branch.branch_name:
            if await self._orgs.branch_name_taken(branch.organization_id, data.branch_name, exclude_id=branch.id):
                raise ConflictError("A branch with this name already exists")
            branch.branch_name = data.branch_name
        if "location" in sent:
            branch.location = data.location
        await self._contacts(branch, data, ctx.user_id)
        branch.updated_by = ctx.user_id
        await self._orgs.commit()
        return await self.get_branch(branch.id, ctx)

    async def delete_branch(self, branch_id: UUID, ctx: RequestContext) -> None:
        branch = await self._get(branch_id, ctx)
        if await self._orgs.count_branches(branch.organization_id) <= 1:
            raise BadRequestError("Cannot delete the organization's last branch")
        if branch.is_head_office:
            raise BadRequestError("This is the head office. Make another branch the head office first")
        me = await self._users.get_user(ctx.user_id)
        if me is not None and me.branch_id == branch.id:
            raise BadRequestError("You cannot delete your own home branch")
        now = _now()
        # Logins homed in the deleted branch can no longer sign in.
        for user in await self._users.list_branch_users(branch.id):
            user.is_active = False
            user.updated_by = ctx.user_id
            await self._users.revoke_sessions(user.id, now)
        branch.soft_delete(ctx.user_id)
        await self._orgs.commit()

    async def reset_login_password(self, branch_id: UUID, new_password: str, ctx: RequestContext) -> None:
        branch = await self._get(branch_id, ctx)
        login = await self._orgs.branch_owner_login(branch.id)
        if login is None:
            raise NotFoundError("Branch login")
        if login.id == ctx.user_id:
            raise BadRequestError("This is your own login — use Change Password instead")
        login.password_hash = hash_password(new_password)
        login.updated_by = ctx.user_id
        await self._users.revoke_sessions(login.id, _now())   # force re-login with the new password
        await self._orgs.commit()
