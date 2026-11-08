"""DB operations for operator accounts, sessions and their RBAC role links. No business logic."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from rbac.models import RBACRole, UserRole
from sqlalchemy import func, select

from app.models.user import User, UserSession
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository):

    async def get_user(self, user_id: UUID) -> User | None:
        stmt = self.alive(User, select(User).where(User.id == user_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> User | None:
        stmt = self.alive(User, select(User).where(func.lower(User.email) == email.lower()))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def count_branch_users(self, branch_id: UUID) -> int:
        stmt = self.alive(User, select(func.count(User.id)).where(User.branch_id == branch_id))
        return (await self._db.execute(stmt)).scalar_one()

    # ── RBAC links ───────────────────────────────────────────────────────
    async def get_role_by_code(self, code: str) -> RBACRole | None:
        stmt = select(RBACRole).where(RBACRole.code == code, RBACRole.deleted_at.is_(None))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_role_codes(self, user_id: UUID) -> list[str]:
        stmt = (select(RBACRole.code)
                .join(UserRole, UserRole.role_id == RBACRole.id)
                .where(UserRole.user_id == user_id, UserRole.is_active.is_(True),
                       UserRole.deleted_at.is_(None), RBACRole.deleted_at.is_(None)))
        return list((await self._db.execute(stmt)).scalars().all())

    async def add_user_role(self, link: UserRole) -> None:
        self._db.add(link)
        await self._db.flush()

    async def user_roles(self, user_id: UUID) -> list[UserRole]:
        stmt = select(UserRole).where(UserRole.user_id == user_id, UserRole.deleted_at.is_(None))
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_employee_login(self, employee_id: UUID) -> User | None:
        """The staff member's account — disabled ones included (is_active=False), so it can be re-enabled."""
        stmt = self.alive(User, select(User).where(User.employee_id == employee_id))
        return (await self._db.execute(stmt)).scalars().first()

    # ── sessions ─────────────────────────────────────────────────────────
    async def get_session(self, session_id: UUID) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.id == session_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def touch_session(self, session: UserSession, at: datetime) -> None:
        session.last_seen_at = at
        await self._db.commit()

    # ── account administration ──────────────────────────────────────────
    async def email_taken(self, email: str) -> bool:
        """Includes soft-deleted accounts — auth_users.email is unique at DB level."""
        stmt = select(User.id).where(func.lower(User.email) == email.lower()).limit(1)
        return (await self._db.execute(stmt)).first() is not None

    async def list_branch_users(self, branch_id: UUID) -> list[User]:
        stmt = self.alive(User, select(User).where(User.branch_id == branch_id))
        return list((await self._db.execute(stmt)).scalars().all())

    async def revoke_sessions(self, user_id: UUID, at: datetime) -> None:
        stmt = select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        for session in (await self._db.execute(stmt)).scalars().all():
            session.revoked_at = at
        await self._db.flush()
