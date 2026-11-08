"""DB operations for gym settings (columns on org_organizations). No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.models.organization import Organization
from app.repositories.base import BaseRepository


class SettingsRepository(BaseRepository):

    async def get_org(self, organization_id: UUID) -> Organization | None:
        stmt = self.alive(Organization, select(Organization).where(Organization.id == organization_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()
