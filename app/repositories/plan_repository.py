"""DB operations for plans. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.enums import PlanServiceType, PlanType
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.training import PTSubscription
from app.repositories.base import BaseRepository


class PlanRepository(BaseRepository):

    async def list_plans(self, scope: BranchScope, *, offset: int, limit: int, search: str | None = None,
                         plan_type: PlanType | None = None,
                         service_type: PlanServiceType | None = None, sort_by: str | None = None,
                         sort_dir: str = "desc") -> tuple[list[Plan], int]:
        stmt = self.scoped(Plan, select(Plan), scope)
        if search:
            stmt = stmt.where(Plan.name.ilike(f"%{search}%"))
        if plan_type:
            stmt = stmt.where(Plan.type == plan_type)
        if service_type:
            stmt = stmt.where(Plan.service_type == service_type)
        columns = {"name": Plan.name, "type": Plan.type, "service_type": Plan.service_type,
                   "duration_days": Plan.duration_days, "price": Plan.price, "created_at": Plan.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir, (Plan.type, Plan.duration_days, Plan.name), Plan.id)
        return await self.paginate_scalars(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope) -> dict[str, int]:
        """all / membership / addon / custom — the list's `type` filter."""
        return await self.count_tabs(self.scoped(Plan, select(Plan), scope), {
            "all": None, "membership": Plan.type == PlanType.MEMBERSHIP, "addon": Plan.type == PlanType.ADD_ON,
            "custom": Plan.type == PlanType.CUSTOM})

    async def get_plan(self, plan_id: UUID, scope: BranchScope) -> Plan | None:
        return await self.get_scoped(Plan, plan_id, scope)

    async def is_in_use(self, plan_id: UUID) -> bool:
        """Any non-deleted subscription or PT subscription referencing the plan."""
        sub = select(Subscription.id).where(Subscription.plan_id == plan_id,
                                            Subscription.is_delete.is_(False)).limit(1)
        if (await self._db.execute(sub)).first() is not None:
            return True
        pt = select(PTSubscription.id).where(PTSubscription.plan_id == plan_id,
                                             PTSubscription.is_delete.is_(False)).limit(1)
        return (await self._db.execute(pt)).first() is not None
