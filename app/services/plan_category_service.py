"""Plan categories — the owner's own list of plan groups (one list for the organization, shared by branches)."""
from __future__ import annotations

from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.models.billing import PlanCategory
from app.repositories.plan_category_repository import PlanCategoryRepository

# A new gym starts with these (all renamable / can be made inactive); nothing in the code depends on the names.
DEFAULT_CATEGORIES = ("General", "Student - School", "Student - College", "Couple", "Family", "Friends",
                      "Corporate", "Personal Training", "Diet", "Add-ons", "Custom duration")


class PlanCategoryService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = PlanCategoryRepository(db)

    @staticmethod
    def category_out(c: PlanCategory, plan_count: int = 0, active_plan_count: int = 0) -> dict:
        return {"id": c.id, "name": c.name, "sort_order": c.sort_order, "is_active": c.is_active,
                "plan_count": plan_count, "active_plan_count": active_plan_count}

    async def create_defaults(self, organization_id: UUID, actor_id: UUID | None) -> None:
        """Onboarding: the starter list. Caller commits."""
        for i, name in enumerate(DEFAULT_CATEGORIES, start=1):
            await self._repo.add(PlanCategory(organization_id=organization_id, name=name, sort_order=i,
                                              created_by=actor_id))

    async def list_categories(self, scope: BranchScope) -> list[dict]:
        return [self.category_out(*row) for row in await self._repo.list_with_counts(scope)]

    async def require(self, category_id: UUID, organization_id: UUID) -> PlanCategory:
        category = await self._repo.get(category_id, organization_id)
        if category is None:
            raise NotFoundError("Plan category")
        return category

    async def create(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        name = data.name.strip()
        if await self._repo.name_taken(scope.organization_id, name):
            raise ConflictError(f"A category named '{name}' already exists")
        category = await self._repo.add(PlanCategory(
            organization_id=scope.organization_id, name=name,
            sort_order=await self._repo.next_sort_order(scope.organization_id), created_by=actor.user_id))
        await self._repo.commit()
        return self.category_out(category)

    async def update(self, category_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        category = await self.require(category_id, scope.organization_id)
        sent = data.model_fields_set
        if "name" in sent and data.name:
            name = data.name.strip()
            if await self._repo.name_taken(scope.organization_id, name, exclude_id=category.id):
                raise ConflictError(f"A category named '{name}' already exists")
            category.name = name
        if "is_active" in sent and data.is_active is not None:
            category.is_active = data.is_active
        category.updated_by = actor.user_id
        await self._repo.commit()
        return self.category_out(category)

    async def reorder(self, ids: list[UUID], scope: BranchScope, actor: RequestContext) -> None:
        by_id = {c.id: c for c in await self._repo.all_for_org(scope.organization_id)}
        if set(ids) != set(by_id):
            raise BadRequestError("Send every category once to reorder")
        for i, cid in enumerate(ids, start=1):
            by_id[cid].sort_order = i
            by_id[cid].updated_by = actor.user_id
        await self._repo.commit()

    async def delete(self, category_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        category = await self.require(category_id, scope.organization_id)
        if await self._repo.has_plans(category.id):
            raise BadRequestError(f"'{category.name}' still has plans. Move or delete them, or make the category inactive")
        category.soft_delete(actor.user_id)
        await self._repo.commit()
