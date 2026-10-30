from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from iam_core.context import RequestContext
from iam_core.exceptions import AuthenticationError

_log = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Extracts JWT from Authorization header, validates it,
    and injects RequestContext into request.state for downstream use.

    Public paths (no JWT required) are configured via skip_paths.
    """

    def __init__(
        self,
        app: ASGIApp,
        token_manager,
        skip_paths: list[str] | None = None,
        skip_prefixes: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._tm = token_manager
        self._skip_paths = set(skip_paths or [])
        self._skip_prefixes = tuple(skip_prefixes or [])

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            if self._should_skip(request):
                return await call_next(request)

            token = self._extract_bearer(request)

            # Support lazy token_manager (passed as lambda for deferred initialisation)
            tm = self._tm() if callable(self._tm) else self._tm
            payload = tm.verify_access_token(token)

            org = payload.get("org")
            request.state.ctx = RequestContext(
                user_id=UUID(payload["sub"]),
                session_id=UUID(payload["sid"]),
                organization_id=UUID(org) if org else None,
                roles=payload.get("roles", []),
                is_superadmin=payload.get("is_superadmin", False),
            )
            # Store raw payload + resolved token_manager for logout (jti blacklisting)
            request.state.jwt_payload = payload
            request.state.token_manager = tm
            return await call_next(request)

        except HTTPException as exc:
            headers = dict(exc.headers) if exc.headers else {}
            return JSONResponse(
                status_code=exc.status_code,
                content={"success": False, "status_code": exc.status_code, "message": exc.detail},
                headers=headers,
            )
        except Exception:
            _log.exception("Unhandled exception in AuthMiddleware")
            return JSONResponse(
                status_code=500,
                content={"success": False, "status_code": 500, "message": "Internal server error"},
            )

    def _should_skip(self, request: Request) -> bool:
        path = request.url.path
        return path in self._skip_paths or (
            bool(self._skip_prefixes) and path.startswith(self._skip_prefixes)
        )

    @staticmethod
    def _extract_bearer(request: Request) -> str:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise AuthenticationError("Missing or invalid Authorization header")
        return auth[7:]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        import uuid
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
