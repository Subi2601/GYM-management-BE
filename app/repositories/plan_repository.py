"""DB operations for plans. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.enums import PlanServiceType, PlanType
from app.core.scope import BranchScope
from app.models.billing import Plan, PlanCategory, Subscription
from app.models.training import PTSubscription
from app.repositories.base import BaseRepository


def _status_condition(status: str | None):
    """active / inactive tab (the plan's own on/off switch); None = every plan."""
    if status == "active":
        return Plan.is_active.is_(True)
    if status == "inactive":
        return Plan.is_active.is_(False)
    return None


class PlanRepository(BaseRepository):

    def _rows(self, scope: BranchScope):
        """(Plan, category name)."""
        stmt = select(Plan, PlanCategory.name).join(PlanCategory, PlanCategory.id == Plan.category_id)
        return self.scoped(Plan, stmt, scope)

    async def list_plans(self, scope: BranchScope, *, offset: int, limit: int, search: str | None = None,
                         plan_type: PlanType | None = None, service_type: PlanServiceType | None = None,
                         category_id: UUID | None = None, active_only: bool = False, status: str | None = None,
                         sort_by: str | None = None, sort_dir: str = "desc") -> tuple[list, int]:
        """Rows (Plan, category name)."""
        stmt = self._rows(scope)
        if search:
            stmt = stmt.where(Plan.name.ilike(f"%{search}%"))
        if plan_type:
            stmt = stmt.where(Plan.type == plan_type)
        if service_type:
            stmt = stmt.where(Plan.service_type == service_type)
        if category_id:
            stmt = stmt.where(Plan.category_id == category_id)
        if active_only:
            stmt = stmt.where(Plan.is_active.is_(True), PlanCategory.is_active.is_(True))
        if (cond := _status_condition(status)) is not None:
            stmt = stmt.where(cond)
        columns = {"name": Plan.name, "type": Plan.type, "service_type": Plan.service_type,
                   "duration_days": Plan.duration_days, "price": Plan.price, "created_at": Plan.created_at}
        # Tariff order: category tabs, then shortest → longest, then cheapest.
        stmt = self.ordered(stmt, columns, sort_by, sort_dir,
                            (PlanCategory.sort_order, Plan.duration_days, Plan.price, Plan.name), Plan.id)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope, *, search: str | None = None,
                         category_id: UUID | None = None) -> dict[str, int]:
        """all / active / inactive (status tabs) + membership / addon / custom, within the search and category."""
        stmt = self.scoped(Plan, select(Plan), scope)
        if search:
            stmt = stmt.where(Plan.name.ilike(f"%{search}%"))
        if category_id:
            stmt = stmt.where(Plan.category_id == category_id)
        return await self.count_tabs(stmt, {
            "all": None, "active": _status_condition("active"), "inactive": _status_condition("inactive"),
            "membership": Plan.type == PlanType.MEMBERSHIP, "addon": Plan.type == PlanType.ADD_ON,
            "custom": Plan.type == PlanType.CUSTOM})

    async def get_plan(self, plan_id: UUID, scope: BranchScope) -> Plan | None:
        return await self.get_scoped(Plan, plan_id, scope)

    async def get_plan_row(self, plan_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._rows(scope).where(Plan.id == plan_id))).first()

    async def is_in_use(self, plan_id: UUID) -> bool:
        """Any non-deleted subscription or PT subscription referencing the plan."""
        sub = select(Subscription.id).where(Subscription.plan_id == plan_id,
                                            Subscription.is_delete.is_(False)).limit(1)
        if (await self._db.execute(sub)).first() is not None:
            return True
        pt = select(PTSubscription.id).where(PTSubscription.plan_id == plan_id,
                                             PTSubscription.is_delete.is_(False)).limit(1)
        return (await self._db.execute(pt)).first() is not None
