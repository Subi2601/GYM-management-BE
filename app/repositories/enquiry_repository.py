"""DB operations for the public enquiry form (branch token, lead lookup by phone). No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update

from app.models.member import Lead
from app.models.organization import Branch, Organization
from app.repositories.base import BaseRepository


class EnquiryRepository(BaseRepository):

    async def branch_by_token(self, token: str) -> tuple[Branch, Organization] | None:
        stmt = (select(Branch, Organization).join(Organization, Organization.id == Branch.organization_id)
                .where(Branch.enquiry_token == token, Branch.deleted_at.is_(None), Organization.deleted_at.is_(None)))
        row = (await self._db.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def get_branch(self, branch_id: UUID, organization_id: UUID) -> Branch | None:
        stmt = self.alive(Branch, select(Branch).where(Branch.id == branch_id,
                                                       Branch.organization_id == organization_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def set_token_if_missing(self, branch: Branch, token: str) -> None:
        """Sets the link token only while none exists, so two first visits racing keep the same token."""
        await self._db.execute(update(Branch).where(Branch.id == branch.id, Branch.enquiry_token.is_(None))
                               .values(enquiry_token=token))
        await self._db.commit()
        await self._db.refresh(branch)

    async def latest_lead_by_phone(self, branch_id: UUID, phone: str) -> Lead | None:
        stmt = (self.alive(Lead, select(Lead).where(Lead.branch_id == branch_id, Lead.phone == phone))
                .order_by(Lead.created_at.desc()).limit(1))
        return (await self._db.execute(stmt)).scalar_one_or_none()
