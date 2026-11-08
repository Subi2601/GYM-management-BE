"""DB operations for the gym profile (organization identity) and its logo / terms files. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import defer

from app.models.organization import Organization, OrgFile
from app.repositories.base import BaseRepository


class GymProfileRepository(BaseRepository):

    async def get_org(self, organization_id: UUID) -> Organization | None:
        stmt = self.alive(Organization, select(Organization).where(Organization.id == organization_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def org_by_code(self, code: str) -> Organization | None:
        stmt = self.alive(Organization, select(Organization).where(Organization.code == code.upper()))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def file(self, organization_id: UUID, kind: str, *, with_data: bool = False) -> OrgFile | None:
        stmt = self.alive(OrgFile, select(OrgFile)).where(OrgFile.organization_id == organization_id,
                                                          OrgFile.kind == kind)
        if not with_data:
            stmt = stmt.options(defer(OrgFile.data))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def files(self, organization_id: UUID) -> dict[str, OrgFile]:
        stmt = (self.alive(OrgFile, select(OrgFile)).options(defer(OrgFile.data))
                .where(OrgFile.organization_id == organization_id))
        return {f.kind: f for f in (await self._db.execute(stmt)).scalars().all()}

    async def hard_delete(self, obj) -> None:
        await self._db.delete(obj)
        await self._db.flush()
