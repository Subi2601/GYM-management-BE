from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class RequestContext:
    """Immutable per-request context injected by AuthMiddleware."""
    user_id: UUID
    session_id: UUID
    organization_id: UUID | None = None   # SaaS tenant (gym business); None only for platform superadmin
    roles: list[str] = field(default_factory=list)
    is_superadmin: bool = False   # True → bypass RBAC entirely
