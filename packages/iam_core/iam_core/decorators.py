from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from iam_core.context import RequestContext
from iam_core.dependencies import get_request_context
from iam_core.exceptions import PermissionDeniedError
from rbac.engine import RBACEngine


def require_permission(permission_code: str):
    """
    Returns an async callable suitable for use with FastAPI's Depends().

    Permission resolution logic:
      - is_superadmin=True  → bypass RBAC entirely
      - otherwise           → check user_roles via RBACEngine

    Usage:
        @router.post("/persons", dependencies=[Depends(require_permission("person:create"))])
        async def create_person(): ...
    """

    async def _check(
        ctx: RequestContext = Depends(get_request_context),
        db: AsyncSession = Depends(_get_db),
    ) -> None:
        if ctx.is_superadmin:
            return

        engine = RBACEngine(db=db)
        allowed = await engine.has_permission(
            user_id=ctx.user_id,
            code=permission_code,
        )

        if not allowed:
            raise PermissionDeniedError(
                f"You do not have permission: '{permission_code}'"
            )

    return _check


# Late-bound import to avoid circular deps.
# The app's main.py overrides this via app.dependency_overrides.
async def _get_db():
    raise NotImplementedError("Override _get_db via dependency_overrides in your app")
