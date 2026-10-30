"""Branch scope — the SaaS data boundary resolved once per request.

organization_id : tenant of the caller (every query filters on it)
branch_id       : the branch the caller is working in; None = "All Branches" (read-only aggregate)
branch_ids      : every branch this request may read
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from shared.exceptions.http_exceptions import BadRequestError


@dataclass(frozen=True)
class BranchScope:
    organization_id: UUID
    branch_id: UUID | None
    branch_ids: tuple[UUID, ...]

    def require_branch(self) -> UUID:
        """Writes always target one branch — "All Branches" is view-only."""
        if self.branch_id is None:
            raise BadRequestError("Select a branch to perform this action")
        return self.branch_id
