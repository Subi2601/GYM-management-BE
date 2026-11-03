"""DB operations for leads. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select

from app.core.enums import LeadStatus
from app.core.scope import BranchScope
from app.models.member import Lead
from app.repositories.base import BaseRepository

REJECTED_STATUSES = (LeadStatus.NOT_INTERESTED, LeadStatus.JOINED_ELSEWHERE)


def _tab_condition(lead_filter: str | None) -> ColumnElement[bool] | None:
    """WHERE clause of a list tab (all / followup / rejected); None = every lead."""
    if lead_filter == "followup":
        return or_(Lead.status == LeadStatus.FOLLOW_UP,
                   and_(Lead.next_follow_up_date.is_not(None), Lead.status != LeadStatus.JOINED))
    if lead_filter == "rejected":
        return Lead.status.in_(REJECTED_STATUSES)
    return None


class LeadRepository(BaseRepository):

    async def list_leads(self, scope: BranchScope, *, offset: int, limit: int, search: str | None = None,
                         lead_filter: str | None = None, status: LeadStatus | None = None,
                         follow_up_from: date | None = None, follow_up_to: date | None = None,
                         sort_by: str | None = None, sort_dir: str = "desc") -> tuple[list[Lead], int]:
        stmt = self.scoped(Lead, select(Lead), scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Lead.name.ilike(pattern), Lead.phone.ilike(pattern)))
        if status:
            stmt = stmt.where(Lead.status == status)
        if follow_up_from:
            stmt = stmt.where(Lead.next_follow_up_date >= follow_up_from)
        if follow_up_to:
            stmt = stmt.where(Lead.next_follow_up_date <= follow_up_to)
        tab = _tab_condition(lead_filter)
        if tab is not None:
            stmt = stmt.where(tab)
        if lead_filter == "followup":
            order = (Lead.next_follow_up_date.asc().nulls_last(), Lead.created_at.desc())
        else:
            order = (Lead.created_at.desc(),)
        columns = {"name": Lead.name, "status": Lead.status, "plan_to_join_date": Lead.plan_to_join_date,
                   "next_follow_up_date": Lead.next_follow_up_date, "created_at": Lead.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir, order, Lead.id)
        return await self.paginate_scalars(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope) -> dict[str, int]:
        tabs = ("all", "followup", "rejected")
        return await self.count_tabs(self.scoped(Lead, select(Lead), scope), {t: _tab_condition(t) for t in tabs})

    async def get_lead(self, lead_id: UUID, scope: BranchScope) -> Lead | None:
        return await self.get_scoped(Lead, lead_id, scope)
