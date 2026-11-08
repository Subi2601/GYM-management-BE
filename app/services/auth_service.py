"""Auth business logic — login, refresh, logout, /me, session enforcement, password change."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from iam_core.exceptions import AuthenticationError
from rbac.engine import RBACEngine
from shared.exceptions.http_exceptions import BadRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import REFRESH_TTL_SECONDS, create_access_token, create_refresh_token, decode_refresh_token
from app.core.security import hash_password, verify_password
from app.models.user import UserSession
from app.repositories.role_repository import RoleRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository

ACCESS_TTL_SECONDS = 4 * 60 * 60
SWITCH_BRANCH_PERMISSION = "branch:switch"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self._users = UserRepository(db)
        self._orgs = OrganizationRepository(db)
        self._rbac = RBACEngine(db)

    async def login(self, email: str, password: str, ip: str | None,
                    user_agent: str | None) -> tuple[str, str]:
        """Returns (access_token, refresh_token). Same message for unknown user / bad password."""
        user = await self._users.get_user_by_email(email.strip())
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        now = _now()
        session = UserSession(user_id=user.id, last_seen_at=now,
                              expires_at=now + timedelta(seconds=REFRESH_TTL_SECONDS),
                              ip_address=ip, user_agent=(user_agent or "")[:255] or None)
        await self._users.add(session)
        user.last_login_at = now
        roles = await self._users.get_role_codes(user.id)
        access = create_access_token(user.id, session.id, roles, user.organization_id, user.is_superadmin)
        refresh = create_refresh_token(user.id, session.id)
        await self._users.commit()
        return access, refresh

    async def refresh(self, refresh_token: str | None) -> tuple[str, str]:
        if not refresh_token:
            raise AuthenticationError("Session expired. Please sign in again.")
        payload = decode_refresh_token(refresh_token)
        session = await self._live_session(UUID(payload["sid"]))
        user = await self._users.get_user(UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise AuthenticationError("Session expired. Please sign in again.")
        now = _now()
        session.last_seen_at = now
        session.expires_at = now + timedelta(seconds=REFRESH_TTL_SECONDS)
        roles = await self._users.get_role_codes(user.id)
        access = create_access_token(user.id, session.id, roles, user.organization_id, user.is_superadmin)
        refresh = create_refresh_token(user.id, session.id)
        await self._users.commit()
        return access, refresh

    async def logout(self, session_id: UUID) -> None:
        session = await self._users.get_session(session_id)
        if session and session.revoked_at is None:
            session.revoked_at = _now()
            await self._users.commit()

    async def enforce_session(self, session_id: UUID) -> None:
        """Called on every authenticated request: revoked / expired / idle sessions are rejected."""
        session = await self._live_session(session_id)
        now = _now()
        if (now - session.last_seen_at).total_seconds() > 60:
            await self._users.touch_session(session, now)

    async def _live_session(self, session_id: UUID) -> UserSession:
        session = await self._users.get_session(session_id)
        now = _now()
        idle = timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
        if (session is None or session.revoked_at is not None or session.expires_at < now
                or now - session.last_seen_at > idle):
            raise AuthenticationError("Session expired. Please sign in again.")
        return session

    async def me(self, user_id: UUID) -> dict:
        user = await self._users.get_user(user_id)
        if user is None:
            raise AuthenticationError()
        tree = await self._rbac.get_user_access(user_id)
        permissions = sorted({p["code"] for m in tree["access"] for s in m["screens"] for p in s["permissions"]})
        can_switch = user.is_superadmin or SWITCH_BRANCH_PERMISSION in permissions
        org_name = org_code = org_logo = None
        branches: list[dict] = []
        if user.organization_id:
            org = await self._orgs.get_organization(user.organization_id)
            org_name, org_code = (org.name, org.code) if org else (None, None)
            if org is not None:
                from app.services.gym_profile_service import GymProfileService
                org_logo = (await GymProfileService(self._users._db).links(org))["logo_url"]
            all_branches = await self._orgs.list_branches(user.organization_id)
            visible = all_branches if can_switch else [b for b in all_branches if b.id == user.branch_id]
            branches = [{"id": b.id, "branch_name": b.branch_name, "location": b.location} for b in visible]
        login_role = max(await RoleRepository(self._users._db).user_roles(user.id), key=lambda r: r.level, default=None)
        return {
            "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role,
                     "role_name": login_role.name if login_role else None,
                     "role_level": login_role.level if login_role else None,
                     "is_superadmin": user.is_superadmin, "organization_id": user.organization_id,
                     "organization_name": org_name, "organization_code": org_code, "organization_logo_url": org_logo,
                     "branch_id": user.branch_id},
            "roles": [r["code"] for r in tree["roles"]],
            "permissions": permissions,
            "access": tree["access"],
            "branches": branches,
            "can_switch_branch": can_switch,
        }

    async def change_password(self, user_id: UUID, current: str, new: str) -> None:
        user = await self._users.get_user(user_id)
        if user is None:
            raise AuthenticationError()
        if not verify_password(current, user.password_hash):
            raise BadRequestError("Current password is incorrect")
        if current == new:
            raise BadRequestError("New password must be different from the current password")
        user.password_hash = hash_password(new)
        await self._users.commit()
