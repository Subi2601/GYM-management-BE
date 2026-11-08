"""Roles & access — each gym's own roles, their level (Owner > Sub-admin > Manager > Staff) and what they can do.

Rules
- Every organization gets OWNER, SUB_ADMIN, MANAGER and STAFF (system roles: can't be deleted) and may add its own.
- Owner always has every permission; its access can't be edited.
- OWNER_ONLY permissions (roles & access, adding / removing branches) can't be given to another role.
- Switching branches ("All Branches") only for roles at ALL_BRANCHES_LEVEL or above.
- Nobody creates, edits or hands out a role at or above their own level.
"""
from __future__ import annotations

import re
from uuid import UUID

from iam_core import RequestContext
from iam_core.exceptions import PermissionDeniedError as ForbiddenError
from rbac.models import RBACRole, RBACRolePermission, UserRole
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AccountRole
from app.core.scope import BranchScope
from app.models.user import User
from app.repositories.role_repository import RoleRepository
from app.utils.rbac_catalog import (ALL_BRANCHES_LEVEL, ALL_BRANCHES_ONLY, LEGACY_ROLE_MAP, MANAGER_LEVEL,
                                    OWNER_LEVEL, OWNER_ONLY, OWNER_ROLE, ROLES, STAFF_LEVEL, SUB_ADMIN_LEVEL)

SUPERADMIN_LEVEL = 1000
# Levels a gym's own role can sit at (the owner level is the owner's alone).
CUSTOM_LEVELS = (SUB_ADMIN_LEVEL, MANAGER_LEVEL, STAFF_LEVEL)
LEVEL_LABEL = {OWNER_LEVEL: "Owner", SUB_ADMIN_LEVEL: "All branches", MANAGER_LEVEL: "Branch manager",
               STAFF_LEVEL: "Branch staff"}


def account_kind(level: int) -> AccountRole:
    """`auth_users.role` is a coarse display field kept in step with the login's role level."""
    if level >= OWNER_LEVEL:
        return AccountRole.OWNER
    return AccountRole.ADMIN if level >= MANAGER_LEVEL else AccountRole.TRAINER


def _code_of(name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_")[:60] or "ROLE"


class RoleService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = RoleRepository(db)

    # ── levels ───────────────────────────────────────────────────────────
    async def level_of(self, user_id: UUID, is_superadmin: bool = False) -> int:
        if is_superadmin:
            return SUPERADMIN_LEVEL
        return max((r.level for r in await self._repo.user_roles(user_id)), default=0)

    async def _actor_level(self, actor: RequestContext) -> int:
        return await self.level_of(actor.user_id, actor.is_superadmin)

    @staticmethod
    def _org(scope: BranchScope) -> UUID:
        if scope.organization_id is None:
            raise BadRequestError("Roles belong to a gym. Sign in with a gym login")
        return scope.organization_id

    # ── setup (seed / onboarding) ────────────────────────────────────────
    async def ensure_org_roles(self, organization_id: UUID, actor_id: UUID | None = None) -> dict[str, RBACRole]:
        """Create the gym's missing system roles with their default access. Existing roles are left as the owner
        set them. Caller commits."""
        perms = await self._repo.permissions_by_code()
        roles: dict[str, RBACRole] = {}
        for code, (name, description, level, grants) in ROLES.items():
            role = await self._repo.get_by_code(organization_id, code)
            if role is None:
                role = await self._repo.add(RBACRole(organization_id=organization_id, code=code, name=name,
                                                     description=description, level=level, is_system=True,
                                                     created_by=actor_id))
                for p_code in grants:
                    if p_code in perms:
                        await self._repo.add(RBACRolePermission(role_id=role.id, screen_id=perms[p_code].screen_id,
                                                                permission_id=perms[p_code].id, is_granted=True))
            elif code == OWNER_ROLE:
                await self._write_grants(role, set(perms), perms)    # owner always has everything (new screens too)
            else:
                await self._roll_out_new(role, grants, perms)
            roles[code] = role
        return roles

    async def move_legacy_logins(self, organization_id: UUID, roles: dict[str, RBACRole]) -> int:
        """Logins still on the old shared OWNER / ADMIN / TRAINER roles → this gym's own roles. Caller commits."""
        legacy = {r.id: r.code for r in await self._repo.legacy_roles()}
        moved = 0
        for user in await self._repo.org_users(organization_id):
            for link in await self._repo.user_links(user.id):
                if link.role_id in legacy:
                    target = roles[LEGACY_ROLE_MAP.get(legacy[link.role_id], "STAFF")]
                    link.role_id = target.id
                    user.role = account_kind(target.level)
                    moved += 1
        await self._repo.flush()
        return moved

    # ── queries ──────────────────────────────────────────────────────────
    async def catalog(self) -> list[dict]:
        """Module → screen → permission tree, with which permissions only the owner (or all-branch roles) can have."""
        modules: dict[UUID, dict] = {}
        for module, screen, perm in await self._repo.catalog():
            m = modules.setdefault(module.id, {"code": module.code, "name": module.name, "icon": module.icon,
                                               "screens": {}})
            s = m["screens"].setdefault(screen.id, {"code": screen.code, "name": screen.name, "permissions": []})
            s["permissions"].append({"code": perm.code, "name": perm.name, "owner_only": perm.code in OWNER_ONLY,
                                     "all_branches_only": perm.code in ALL_BRANCHES_ONLY})
        return [{**m, "screens": list(m["screens"].values())} for m in modules.values()]

    def _role_out(self, r: RBACRole, users: int, grants: int, actor_level: int) -> dict:
        return {"id": r.id, "code": r.code, "name": r.name, "description": r.description, "level": r.level,
                "level_label": LEVEL_LABEL.get(r.level, f"Level {r.level}"),
                "all_branches": r.level >= ALL_BRANCHES_LEVEL, "is_system": r.is_system,
                "is_owner": r.code == OWNER_ROLE, "user_count": users, "permission_count": grants,
                "editable": r.code != OWNER_ROLE and r.level < actor_level}

    async def list_roles(self, scope: BranchScope, actor: RequestContext) -> list[dict]:
        roles = await self._repo.org_roles(self._org(scope))
        ids = [r.id for r in roles]
        users, grants = await self._repo.user_counts(ids), await self._repo.grant_counts(ids)
        level = await self._actor_level(actor)
        return [self._role_out(r, users.get(r.id, 0), grants.get(r.id, 0), level) for r in roles]

    async def _role(self, role_id: UUID, scope: BranchScope) -> RBACRole:
        role = await self._repo.get_role(role_id, self._org(scope))
        if role is None:
            raise NotFoundError("Role")
        return role

    async def get_role(self, role_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        role = await self._role(role_id, scope)
        codes = await self._repo.granted_codes(role.id)
        users = (await self._repo.user_counts([role.id])).get(role.id, 0)
        return {**self._role_out(role, users, len(codes), await self._actor_level(actor)), "permissions": sorted(codes)}

    async def assignable(self, scope: BranchScope, actor: RequestContext) -> list[dict]:
        """Roles the actor may give a staff login: below their own level, never Owner."""
        level = await self._actor_level(actor)
        return [r for r in await self.list_roles(scope, actor) if not r["is_owner"] and r["level"] < level]

    # ── commands ─────────────────────────────────────────────────────────
    async def _check_editable(self, role: RBACRole, actor: RequestContext) -> None:
        if role.code == OWNER_ROLE:
            raise BadRequestError("The owner always has full access")
        if role.level >= await self._actor_level(actor):
            raise ForbiddenError("You can only change roles below your own level")

    async def _check_level(self, level: int, actor: RequestContext) -> None:
        if level not in CUSTOM_LEVELS:
            raise BadRequestError("Pick All branches, Branch manager or Branch staff")
        if level >= await self._actor_level(actor):
            raise ForbiddenError("A role must be below your own level")

    async def create_role(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        org = self._org(scope)
        await self._check_level(data.level, actor)
        name = data.name.strip()
        if await self._repo.name_taken(org, name):
            raise ConflictError(f"A role called {name} already exists")
        base, code, n = _code_of(name), _code_of(name), 1
        while await self._repo.get_by_code(org, code) is not None:
            n += 1
            code = f"{base}_{n}"
        role = await self._repo.add(RBACRole(organization_id=org, code=code, name=name,
                                             description=(data.description or "").strip() or None, level=data.level,
                                             is_system=False, created_by=actor.user_id))
        # Start from a role of the same level (or the one picked), so the owner only adjusts the ticks.
        source = None
        if data.copy_from_id:
            source = await self._role(data.copy_from_id, scope)
        else:
            source = next((r for r in await self._repo.org_roles(org) if r.is_system and r.level == data.level), None)
        if source is not None:
            await self._set_codes(role, set(await self._repo.granted_codes(source.id)))
        await self._repo.commit()
        return await self.get_role(role.id, scope, actor)

    async def update_role(self, role_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        role = await self._role(role_id, scope)
        await self._check_editable(role, actor)
        sent = data.model_fields_set
        if "name" in sent and data.name:
            name = data.name.strip()
            if await self._repo.name_taken(role.organization_id, name, exclude_id=role.id):
                raise ConflictError(f"A role called {name} already exists")
            role.name = name
        if "description" in sent:
            role.description = (data.description or "").strip() or None
        if "level" in sent and data.level is not None and data.level != role.level:
            if role.is_system:
                raise BadRequestError("The level of a built-in role can't change")
            await self._check_level(data.level, actor)
            role.level = data.level
            await self._sync_users(role)
            if role.level < ALL_BRANCHES_LEVEL:                       # dropped below all-branch: no switching
                codes = set(await self._repo.granted_codes(role.id)) - ALL_BRANCHES_ONLY
                await self._set_codes(role, codes)
        role.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_role(role.id, scope, actor)

    async def set_permissions(self, role_id: UUID, codes: list[str], scope: BranchScope,
                              actor: RequestContext) -> dict:
        role = await self._role(role_id, scope)
        await self._check_editable(role, actor)
        wanted = set(codes)
        owner_only = sorted(wanted & OWNER_ONLY)
        if owner_only:
            raise BadRequestError(f"Only the owner can have: {', '.join(owner_only)}")
        if role.level < ALL_BRANCHES_LEVEL and wanted & ALL_BRANCHES_ONLY:
            raise BadRequestError("Switching branches is only for All branches roles")
        known = await self._repo.permissions_by_code(list(wanted))
        unknown = sorted(wanted - set(known))
        if unknown:
            raise BadRequestError(f"Unknown permissions: {', '.join(unknown)}")
        wanted.add("auth:me")                                        # every login can see its own account
        await self._set_codes(role, wanted)
        role.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_role(role.id, scope, actor)

    async def delete_role(self, role_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        role = await self._role(role_id, scope)
        await self._check_editable(role, actor)
        if role.is_system:
            raise BadRequestError("Built-in roles can't be deleted")
        users = (await self._repo.user_counts([role.id])).get(role.id, 0)
        if users:
            raise BadRequestError(f"{users} login(s) use {role.name}. Give them another role first")
        for link in await self._repo.links_of_role(role.id):
            link.soft_delete(actor.user_id)
        for grant in await self._repo.grant_rows(role.id):
            if grant.deleted_at is None:
                grant.soft_delete(actor.user_id)
        role.soft_delete(actor.user_id)
        await self._repo.commit()

    async def assign(self, user: User, role_id: UUID, scope: BranchScope, actor: RequestContext) -> RBACRole:
        """Give a login one role (re-points its existing link). Checks the hierarchy. Caller commits."""
        role = await self._role(role_id, scope)
        if role.code == OWNER_ROLE:
            raise BadRequestError("The owner role can't be given to a staff login")
        if role.level >= await self._actor_level(actor):
            raise ForbiddenError(f"You can't give {role.name}: it is at or above your own level")
        links = await self._repo.user_links(user.id)
        if links:
            links[0].role_id, links[0].is_active, links[0].assigned_by = role.id, True, actor.user_id
            for extra in links[1:]:
                await self._repo.delete(extra)
        else:
            await self._repo.add(UserRole(user_id=user.id, role_id=role.id, assigned_by=actor.user_id))
        user.role = account_kind(role.level)
        return role

    async def role_by_code(self, organization_id: UUID, code: str) -> RBACRole:
        role = await self._repo.get_by_code(organization_id, code)
        if role is None or role.deleted_at is not None:
            raise BadRequestError(f"{code} role is missing for this gym — run the seed")
        return role

    async def login_role(self, user_id: UUID) -> RBACRole | None:
        roles = await self._repo.user_roles(user_id)
        return max(roles, key=lambda r: r.level) if roles else None

    # ── internals ────────────────────────────────────────────────────────
    async def _set_codes(self, role: RBACRole, codes: set[str]) -> None:
        await self._write_grants(role, codes, await self._repo.permissions_by_code())

    async def _write_grants(self, role: RBACRole, codes: set[str], perms: dict) -> None:
        """Make the role's grants exactly `codes`: revive / update existing rows (unique key), add missing ones."""
        rows = {g.permission_id: g for g in await self._repo.grant_rows(role.id)}
        wanted_ids = {perms[c].id for c in codes if c in perms}
        for perm_id, row in rows.items():
            if perm_id in wanted_ids:
                row.deleted_at, row.is_delete, row.is_granted = None, False, True
            elif row.deleted_at is None:
                row.soft_delete()
        for code in codes:
            p = perms.get(code)
            if p is not None and p.id not in rows:
                await self._repo.add(RBACRolePermission(role_id=role.id, screen_id=p.screen_id, permission_id=p.id,
                                                        is_granted=True))
        await self._repo.flush()

    async def _roll_out_new(self, role: RBACRole, defaults: list[str], perms: dict) -> None:
        """A built-in role gets permissions added to its defaults after it was created (new screens), but only
        those the owner never decided on: any grant row, even a removed one, means the owner chose."""
        decided = {g.permission_id for g in await self._repo.grant_rows(role.id)}
        for code in defaults:
            p = perms.get(code)
            if p is not None and p.id not in decided:
                await self._repo.add(RBACRolePermission(role_id=role.id, screen_id=p.screen_id, permission_id=p.id,
                                                        is_granted=True))

    async def _sync_users(self, role: RBACRole) -> None:
        for link in await self._repo.links_of_role(role.id):
            user = await self._repo._db.get(User, link.user_id)
            if user is not None:
                user.role = account_kind(role.level)
