"""DB operations for the food catalogue. No business logic.

FoodItem is organization-level, not branch-scoped: organization_id NULL = platform catalogue,
otherwise the gym's own foods. Gyms see both.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select

from app.core.enums import FoodCategory
from app.models.diet import DietPlanItem, FoodItem
from app.repositories.base import BaseRepository


class FoodRepository(BaseRepository):

    @staticmethod
    def _visible(organization_id: UUID):
        return BaseRepository.alive(FoodItem, select(FoodItem)).where(
            or_(FoodItem.organization_id.is_(None), FoodItem.organization_id == organization_id))

    async def list_foods(self, organization_id: UUID, *, offset: int, limit: int,
                         category: FoodCategory | None = None, search: str | None = None) -> tuple[list, int]:
        stmt = self._visible(organization_id)
        if category:
            stmt = stmt.where(FoodItem.category == category)
        if search:
            stmt = stmt.where(FoodItem.name.ilike(f"%{search}%"))
        return await self.paginate_scalars(stmt.order_by(FoodItem.name, FoodItem.id), offset=offset, limit=limit)

    async def get_visible(self, food_id: UUID, organization_id: UUID) -> FoodItem | None:
        stmt = self._visible(organization_id).where(FoodItem.id == food_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_by_name(self, organization_id: UUID, name: str) -> FoodItem | None:
        stmt = self._visible(organization_id).where(func.lower(FoodItem.name) == name.lower()).limit(1)
        return (await self._db.execute(stmt)).scalars().first()

    async def is_used_in_plans(self, food_id: UUID) -> bool:
        stmt = select(DietPlanItem.id).where(DietPlanItem.food_item_id == food_id).limit(1)
        return (await self._db.execute(stmt)).first() is not None
