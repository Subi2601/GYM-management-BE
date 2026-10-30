"""Food catalogue business logic — platform vs gym-owned foods, delete guards."""
from __future__ import annotations

from uuid import UUID

from iam_core import RequestContext
from iam_core.exceptions import PermissionDeniedError
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FoodCategory
from app.core.scope import BranchScope
from app.models.diet import FoodItem
from app.repositories.food_repository import FoodRepository

_FIELDS = ("name", "category", "calories", "protein", "carbs", "fats", "fiber", "serving_unit",
           "nutritional_benefits", "image_url")


class FoodService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = FoodRepository(db)

    @staticmethod
    def food_out(f: FoodItem) -> dict:
        return {"id": f.id, "organization_id": f.organization_id, "is_platform": f.organization_id is None,
                **{k: getattr(f, k) for k in _FIELDS},
                "created_at": f.created_at, "updated_at": f.updated_at}

    async def list_foods(self, scope: BranchScope, *, offset: int, limit: int, category: FoodCategory | None,
                         search: str | None) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_foods(scope.organization_id, offset=offset, limit=limit,
                                                  category=category, search=search)
        return [self.food_out(f) for f in rows], total

    async def create_food(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        if await self._repo.get_by_name(scope.organization_id, data.name):
            raise ConflictError("A food item with this name already exists")
        food = FoodItem(organization_id=scope.organization_id, **{k: getattr(data, k) for k in _FIELDS},
                        created_by=actor.user_id)
        await self._repo.add(food)
        await self._repo.commit()
        await self._repo.refresh(food)
        return self.food_out(food)

    async def delete_food(self, food_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        food = await self._repo.get_visible(food_id, scope.organization_id)
        if food is None:
            raise NotFoundError("Food item")
        if food.organization_id is None:
            raise PermissionDeniedError("Platform catalogue items cannot be deleted")
        if await self._repo.is_used_in_plans(food.id):
            raise BadRequestError("Cannot delete food item: it is used in a diet plan")
        food.soft_delete(actor.user_id)
        await self._repo.commit()
