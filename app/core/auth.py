# JWT HS256 encode/decode — thin wrapper over iam_core.TokenManager
import time
from uuid import UUID, uuid4

import jwt
from iam_core import TokenManager
from iam_core.exceptions import InvalidTokenError, TokenExpiredError

from app.config import settings

REFRESH_TTL_SECONDS = TokenManager.REFRESH_TTL_SECONDS  # 1 day
REFRESH_COOKIE_NAME = "stag_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"

_token_manager: TokenManager | None = None


def get_token_manager() -> TokenManager:
    """Lazy singleton, built on first use."""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager(settings.JWT_SECRET)
    return _token_manager


def create_access_token(user_id: UUID, session_id: UUID, roles: list[str],
                        organization_id: UUID | None, is_superadmin: bool = False) -> str:
    """HS256 access token, 4-hour TTL."""
    return get_token_manager().issue_access_token(
        user_id=user_id, session_id=session_id, roles=roles,
        is_superadmin=is_superadmin, organization_id=organization_id,
    )


def create_refresh_token(user_id: UUID, session_id: UUID) -> str:
    """HS256 refresh token, 1-day TTL. Delivered ONLY as an httpOnly cookie."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "typ": "refresh",
        "iat": now,
        "exp": now + REFRESH_TTL_SECONDS,
        "jti": str(uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=TokenManager.ALGORITHM)


def decode_refresh_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[TokenManager.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.InvalidTokenError:
        raise InvalidTokenError()
    if payload.get("typ") != "refresh":
        raise InvalidTokenError()
    return payload
