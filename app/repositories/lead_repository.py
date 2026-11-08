"""DB operations for leads. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.orm import aliased

from app.core.enums import LeadSource, LeadStatus
from app.core.scope import BranchScope

from app.models.member import Lead, Member
from app.models.user import User
from app.repositories.base import BaseRepository

REJECTED_STATUSES = (LeadStatus.NOT_INTERESTED, LeadStatus.JOINED_ELSEWHERE)


LEAD_TABS = ("all", "followup", "trial", "rejected")


def _tab_condition(lead_filter: str | None) -> ColumnElement[bool] | None:
    """WHERE clause of a list tab (all / followup / trial / rejected); None = every lead."""
    if lead_filter == "followup":
        return or_(Lead.status == LeadStatus.FOLLOW_UP,
                   and_(Lead.next_follow_up_date.is_not(None), Lead.status != LeadStatus.JOINED))
    if lead_filter == "trial":       # booked a trial and still open (not joined / not dropped)
        return and_(Lead.trial_start.is_not(None), Lead.status.in_((LeadStatus.NEW, LeadStatus.FOLLOW_UP)))
    if lead_filter == "rejected":
        return Lead.status.in_(REJECTED_STATUSES)
    return None


class LeadRepository(BaseRepository):

    def _rows(self, scope: BranchScope):
        """(Lead, name of the account that took the enquiry, name of the referring member)."""
        referrer = aliased(Member)
        stmt = (select(Lead, User.name, referrer.name).outerjoin(User, User.id == Lead.created_by)
                .outerjoin(referrer, referrer.id == Lead.referred_by_id))
        return self.scoped(Lead, stmt, scope)

    async def list_leads(self, scope: BranchScope, *, offset: int, limit: int, search: str | None = None,
                         lead_filter: str | None = None, status: LeadStatus | None = None,
                         source: LeadSource | None = None, attended_by: UUID | None = None,
                         follow_up_from: date | None = None, follow_up_to: date | None = None,
                         sort_by: str | None = None, sort_dir: str = "desc") -> tuple[list, int]:
        """Rows: (Lead, attended-by name)."""
        stmt = self._rows(scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Lead.name.ilike(pattern), Lead.phone.ilike(pattern)))
        if status:
            stmt = stmt.where(Lead.status == status)
        if source:
            stmt = stmt.where(Lead.source == source)
        if attended_by:
            stmt = stmt.where(Lead.created_by == attended_by)
        if follow_up_from:
            stmt = stmt.where(Lead.next_follow_up_date >= follow_up_from)
        if follow_up_to:
            stmt = stmt.where(Lead.next_follow_up_date <= follow_up_to)
        tab = _tab_condition(lead_filter)
        if tab is not None:
            stmt = stmt.where(tab)
        if lead_filter == "followup":
            order = (Lead.next_follow_up_date.asc().nulls_last(), Lead.created_at.desc())
        elif lead_filter == "trial":
            order = (Lead.trial_end.asc(), Lead.created_at.desc())
        else:
            order = (Lead.created_at.desc(),)
        columns = {"name": Lead.name, "status": Lead.status, "source": Lead.source,
                   "plan_to_join_date": Lead.plan_to_join_date, "next_follow_up_date": Lead.next_follow_up_date,
                   "trial_start": Lead.trial_start, "created_at": Lead.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir, order, Lead.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope) -> dict[str, int]:
        return await self.count_tabs(self.scoped(Lead, select(Lead), scope),
                                     {t: _tab_condition(t) for t in LEAD_TABS})

    async def get_lead(self, lead_id: UUID, scope: BranchScope) -> Lead | None:
        return await self.get_scoped(Lead, lead_id, scope)

    async def get_lead_row(self, lead_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._rows(scope).where(Lead.id == lead_id))).first()

    async def attendants(self, scope: BranchScope) -> list:
        """Accounts that have added leads in scope: rows (id, name), by name."""
        stmt = (select(User.id, User.name).join(Lead, Lead.created_by == User.id)
                .where(Lead.organization_id == scope.organization_id, Lead.branch_id.in_(scope.branch_ids),
                       Lead.is_delete.is_(False))
                .distinct().order_by(User.name.asc()))
        return list((await self._db.execute(stmt)).all())

    async def user_name(self, user_id: UUID) -> str | None:
        return (await self._db.execute(select(User.name).where(User.id == user_id))).scalar_one_or_none()
