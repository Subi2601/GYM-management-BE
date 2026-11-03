# get_db, get_current_user (iam_core integration), branch scope, PII access
from typing import AsyncGenerator

from fastapi import Depends, Header
from iam_core import RequestContext
from iam_core.dependencies import get_request_context
from iam_core.exceptions import PermissionDeniedError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.database import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    ctx: RequestContext = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
) -> RequestContext:
    """AuthMiddleware validated signature/expiry; this rejects revoked, expired and idle sessions."""
    from app.services.auth_service import AuthService

    await AuthService(db).enforce_session(ctx.session_id)
    return ctx


async def get_branch_scope(
    x_branch_id: str | None = Header(default=None, alias="X-Branch-ID"),
    ctx: RequestContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BranchScope:
    """Tenant + branch the request operates on. Header absent → home branch (or all branches
    for accounts holding branch:switch)."""
    from app.services.scope_service import ScopeService

    return await ScopeService(db).resolve(ctx, x_branch_id)


async def get_pii_access(
    ctx: RequestContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> bool:
    """True → caller sees decrypted Aadhaar/PAN/ID/bank numbers; False → masked."""
    from app.services.scope_service import ScopeService

    return await ScopeService(db).can_view_pii(ctx)


async def get_payroll_access(
    ctx: RequestContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> bool:
    """True → caller may see salary payouts (salary:list) inside other screens, e.g. the staff profile."""
    from app.services.scope_service import ScopeService

    return await ScopeService(db).can_view_payroll(ctx)


async def require_superadmin(ctx: RequestContext = Depends(get_current_user)) -> RequestContext:
    if not ctx.is_superadmin:
        raise PermissionDeniedError("Platform superadmin access required")
    return ctx
