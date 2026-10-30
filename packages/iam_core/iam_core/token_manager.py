from __future__ import annotations

import hashlib
import secrets
import time
from uuid import UUID, uuid4

import jwt


class TokenManager:
    """Issues and verifies JWTs using HS256 with a single shared secret. No Redis dependency.
    `org` claim carries the SaaS organization (tenant) of the user."""

    ALGORITHM = "HS256"
    ACCESS_TTL_SECONDS = 4 * 60 * 60      # 4 hours per TESS spec
    REFRESH_TTL_SECONDS = 24 * 60 * 60    # 1 day per TESS spec

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def issue_access_token(
        self,
        user_id: UUID,
        session_id: UUID,
        roles: list,
        is_superadmin: bool = False,
        ttl_seconds: int | None = None,
        organization_id: UUID | None = None,
    ) -> str:
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "sid": str(session_id),
            "org": str(organization_id) if organization_id else None,
            "roles": roles,
            "is_superadmin": is_superadmin,
            "typ": "access",
            "iat": now,
            "exp": now + (ttl_seconds or self.ACCESS_TTL_SECONDS),
            "jti": str(uuid4()),
        }
        return jwt.encode(payload, self._secret, algorithm=self.ALGORITHM)

    def verify_access_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self.ALGORITHM])
        except jwt.ExpiredSignatureError:
            from iam_core.exceptions import TokenExpiredError
            raise TokenExpiredError()
        except jwt.InvalidTokenError:
            from iam_core.exceptions import InvalidTokenError
            raise InvalidTokenError()
        if payload.get("typ") != "access":
            from iam_core.exceptions import InvalidTokenError
            raise InvalidTokenError()
        return payload

    @staticmethod
    def generate_refresh_token() -> tuple[str, str]:
        """Returns (raw_token, sha256_hash). Store only the hash."""
        raw = secrets.token_urlsafe(64)
        hashed = hashlib.sha256(raw.encode()).hexdigest()
        return raw, hashed
