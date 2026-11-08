"""DB operations for plan categories. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, select

from app.core.scope import BranchScope
from app.models.billing import Plan, PlanCategory
from app.repositories.base import BaseRepository


class PlanCategoryRepository(BaseRepository):

    async def list_with_counts(self, scope: BranchScope) -> list:
        """Rows (category, plans in scope, active plans in scope), in tab order."""
        plan_in_scope = and_(Plan.category_id == PlanCategory.id, Plan.organization_id == scope.organization_id,
                             Plan.branch_id.in_(scope.branch_ids), Plan.is_delete.is_(False))
        total = select(func.count(Plan.id)).where(plan_in_scope).scalar_subquery()
        active = select(func.count(Plan.id)).where(plan_in_scope, Plan.is_active.is_(True)).scalar_subquery()
        stmt = self.alive(PlanCategory, select(PlanCategory, total, active)
                          .where(PlanCategory.organization_id == scope.organization_id))
        return list((await self._db.execute(stmt.order_by(PlanCategory.sort_order, PlanCategory.name))).all())

    async def get(self, category_id: UUID, organization_id: UUID) -> PlanCategory | None:
        stmt = self.alive(PlanCategory, select(PlanCategory).where(PlanCategory.id == category_id,
                                                                   PlanCategory.organization_id == organization_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def all_for_org(self, organization_id: UUID) -> list[PlanCategory]:
        stmt = self.alive(PlanCategory, select(PlanCategory).where(PlanCategory.organization_id == organization_id))
        return list((await self._db.execute(stmt.order_by(PlanCategory.sort_order))).scalars().all())

    async def name_taken(self, organization_id: UUID, name: str, exclude_id: UUID | None = None) -> bool:
        stmt = self.alive(PlanCategory, select(PlanCategory.id).where(
            PlanCategory.organization_id == organization_id, func.lower(PlanCategory.name) == name.lower()))
        if exclude_id:
            stmt = stmt.where(PlanCategory.id != exclude_id)
        return (await self._db.execute(stmt.limit(1))).first() is not None

    async def has_plans(self, category_id: UUID) -> bool:
        stmt = self.alive(Plan, select(Plan.id).where(Plan.category_id == category_id)).limit(1)
        return (await self._db.execute(stmt)).first() is not None

    async def next_sort_order(self, organization_id: UUID) -> int:
        stmt = select(func.coalesce(func.max(PlanCategory.sort_order), 0)).where(
            PlanCategory.organization_id == organization_id, PlanCategory.is_delete.is_(False))
        return int((await self._db.execute(stmt)).scalar_one()) + 1
