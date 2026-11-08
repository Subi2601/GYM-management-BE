"""DB operations for a gym's roles and their access (rbac_* tables). No business logic."""
from __future__ import annotations

from uuid import UUID

from rbac.models import RBACModule, RBACPermission, RBACRole, RBACRolePermission, RBACScreen, UserRole
from sqlalchemy import func, select

from app.models.user import User
from app.repositories.base import BaseRepository


class RoleRepository(BaseRepository):

    # ── catalogue ────────────────────────────────────────────────────────
    async def catalog(self) -> list[tuple[RBACModule, RBACScreen, RBACPermission]]:
        stmt = (select(RBACModule, RBACScreen, RBACPermission)
                .join(RBACScreen, RBACScreen.module_id == RBACModule.id)
                .join(RBACPermission, RBACPermission.screen_id == RBACScreen.id)
                .where(RBACModule.deleted_at.is_(None), RBACScreen.deleted_at.is_(None),
                       RBACPermission.deleted_at.is_(None))
                .order_by(RBACModule.sort_order, RBACScreen.sort_order, RBACPermission.code))
        return [tuple(r) for r in (await self._db.execute(stmt)).all()]

    async def permissions_by_code(self, codes: list[str] | None = None) -> dict[str, RBACPermission]:
        stmt = select(RBACPermission).where(RBACPermission.deleted_at.is_(None))
        if codes is not None:
            stmt = stmt.where(RBACPermission.code.in_(codes))
        return {p.code: p for p in (await self._db.execute(stmt)).scalars()}

    # ── roles ────────────────────────────────────────────────────────────
    async def org_roles(self, organization_id: UUID) -> list[RBACRole]:
        stmt = (select(RBACRole).where(RBACRole.organization_id == organization_id, RBACRole.deleted_at.is_(None))
                .order_by(RBACRole.level.desc(), RBACRole.name))
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_role(self, role_id: UUID, organization_id: UUID) -> RBACRole | None:
        stmt = select(RBACRole).where(RBACRole.id == role_id, RBACRole.organization_id == organization_id,
                                      RBACRole.deleted_at.is_(None))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_by_code(self, organization_id: UUID, code: str) -> RBACRole | None:
        stmt = select(RBACRole).where(RBACRole.organization_id == organization_id, RBACRole.code == code)
        return (await self._db.execute(stmt)).scalar_one_or_none()     # includes deleted: codes stay unique

    async def name_taken(self, organization_id: UUID, name: str, exclude_id: UUID | None = None) -> bool:
        stmt = select(RBACRole.id).where(RBACRole.organization_id == organization_id,
                                         func.lower(RBACRole.name) == name.lower(), RBACRole.deleted_at.is_(None))
        if exclude_id:
            stmt = stmt.where(RBACRole.id != exclude_id)
        return (await self._db.execute(stmt.limit(1))).first() is not None

    async def legacy_roles(self) -> list[RBACRole]:
        """The old shared OWNER / ADMIN / TRAINER rows (no organization)."""
        stmt = select(RBACRole).where(RBACRole.organization_id.is_(None), RBACRole.deleted_at.is_(None))
        return list((await self._db.execute(stmt)).scalars().all())

    # ── grants ───────────────────────────────────────────────────────────
    async def granted_codes(self, role_id: UUID) -> list[str]:
        stmt = (select(RBACPermission.code).join(RBACRolePermission, RBACRolePermission.permission_id == RBACPermission.id)
                .where(RBACRolePermission.role_id == role_id, RBACRolePermission.is_granted.is_(True),
                       RBACRolePermission.deleted_at.is_(None), RBACPermission.deleted_at.is_(None)))
        return list((await self._db.execute(stmt)).scalars().all())

    async def grant_counts(self, role_ids: list[UUID]) -> dict[UUID, int]:
        if not role_ids:
            return {}
        stmt = (select(RBACRolePermission.role_id, func.count())
                .where(RBACRolePermission.role_id.in_(role_ids), RBACRolePermission.is_granted.is_(True),
                       RBACRolePermission.deleted_at.is_(None))
                .group_by(RBACRolePermission.role_id))
        return dict((await self._db.execute(stmt)).all())

    async def grant_rows(self, role_id: UUID) -> list[RBACRolePermission]:
        """Every grant row of the role, soft-deleted ones too (the unique key still counts them)."""
        stmt = select(RBACRolePermission).where(RBACRolePermission.role_id == role_id)
        return list((await self._db.execute(stmt)).scalars().all())

    # ── users ────────────────────────────────────────────────────────────
    async def user_counts(self, role_ids: list[UUID]) -> dict[UUID, int]:
        if not role_ids:
            return {}
        stmt = (select(UserRole.role_id, func.count())
                .join(User, User.id == UserRole.user_id)
                .where(UserRole.role_id.in_(role_ids), UserRole.is_active.is_(True), UserRole.deleted_at.is_(None),
                       User.deleted_at.is_(None), User.is_active.is_(True))
                .group_by(UserRole.role_id))
        return dict((await self._db.execute(stmt)).all())

    async def user_roles(self, user_id: UUID) -> list[RBACRole]:
        stmt = (select(RBACRole).join(UserRole, UserRole.role_id == RBACRole.id)
                .where(UserRole.user_id == user_id, UserRole.is_active.is_(True), UserRole.deleted_at.is_(None),
                       RBACRole.deleted_at.is_(None)))
        return list((await self._db.execute(stmt)).scalars().all())

    async def links_of_role(self, role_id: UUID) -> list[UserRole]:
        stmt = select(UserRole).where(UserRole.role_id == role_id, UserRole.deleted_at.is_(None))
        return list((await self._db.execute(stmt)).scalars().all())

    async def org_users(self, organization_id: UUID) -> list[User]:
        stmt = select(User).where(User.organization_id == organization_id)
        return list((await self._db.execute(stmt)).scalars().all())

    async def user_links(self, user_id: UUID) -> list[UserRole]:
        stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.deleted_at.is_(None))
        return list((await self._db.execute(stmt)).scalars().all())
