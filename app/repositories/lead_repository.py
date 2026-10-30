"""DB operations for leads. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select

from app.core.enums import LeadStatus
from app.core.scope import BranchScope
from app.models.member import Lead
from app.repositories.base import BaseRepository

REJECTED_STATUSES = (LeadStatus.NOT_INTERESTED, LeadStatus.JOINED_ELSEWHERE)


class LeadRepository(BaseRepository):

    async def list_leads(self, scope: BranchScope, *, offset: int, limit: int, search: str | None = None,
                         lead_filter: str | None = None) -> tuple[list[Lead], int]:
        stmt = self.scoped(Lead, select(Lead), scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Lead.name.ilike(pattern), Lead.phone.ilike(pattern)))
        if lead_filter == "followup":
            stmt = stmt.where(or_(Lead.status == LeadStatus.FOLLOW_UP,
                                  and_(Lead.next_follow_up_date.is_not(None), Lead.status != LeadStatus.JOINED)))
            order = (Lead.next_follow_up_date.asc().nulls_last(), Lead.created_at.desc())
        else:
            if lead_filter == "rejected":
                stmt = stmt.where(Lead.status.in_(REJECTED_STATUSES))
            order = (Lead.created_at.desc(),)
        return await self.paginate_scalars(stmt.order_by(*order), offset=offset, limit=limit)

    async def get_lead(self, lead_id: UUID, scope: BranchScope) -> Lead | None:
        return await self.get_scoped(Lead, lead_id, scope)
