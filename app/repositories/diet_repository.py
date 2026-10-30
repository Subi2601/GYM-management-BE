"""DB operations for diet plans and diet eligibility. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select

from app.core.enums import PlanServiceType, PlanType
from app.core.scope import BranchScope
from app.models.billing import Plan, Subscription
from app.models.diet import DietPlan, DietPlanItem, FoodItem
from app.models.member import Member
from app.repositories.base import BaseRepository

LONG_MEMBERSHIP_DAYS = 90


class DietRepository(BaseRepository):

    # ── eligibility inputs ───────────────────────────────────────────────
    @staticmethod
    def _latest_diet_addon():
        """Latest DIET add-on subscription per member → plan name."""
        rn = func.row_number().over(partition_by=Subscription.member_id,
                                    order_by=(Subscription.start_date.desc(), Subscription.created_at.desc()))
        inner = (select(Subscription.member_id, Plan.name.label("plan_name"), rn.label("rn"))
                 .join(Plan, Plan.id == Subscription.plan_id)
                 .where(Subscription.is_delete.is_(False), Plan.type == PlanType.ADD_ON,
                        Plan.service_type == PlanServiceType.DIET)
                 .subquery())
        return select(inner.c.member_id, inner.c.plan_name).where(inner.c.rn == 1).subquery()

    @staticmethod
    def _long_membership():
        """Members holding any MEMBERSHIP subscription of ≥ 90 days."""
        return (select(Subscription.member_id)
                .join(Plan, Plan.id == Subscription.plan_id)
                .where(Subscription.is_delete.is_(False), Plan.type == PlanType.MEMBERSHIP,
                       Plan.duration_days >= LONG_MEMBERSHIP_DAYS)
                .group_by(Subscription.member_id)
                .subquery())

    def _eligibility_stmt(self, scope: BranchScope):
        diet = self._latest_diet_addon()
        longm = self._long_membership()
        plan = (select(DietPlan.member_id, DietPlan.id, DietPlan.tier, DietPlan.last_modified_date)
                .where(DietPlan.is_delete.is_(False)).subquery())
        stmt = (select(Member, diet.c.plan_name, longm.c.member_id.is_not(None).label("long_membership"),
                       plan.c.id, plan.c.tier, plan.c.last_modified_date)
                .outerjoin(diet, diet.c.member_id == Member.id)
                .outerjoin(longm, longm.c.member_id == Member.id)
                .outerjoin(plan, plan.c.member_id == Member.id)
                .where(or_(diet.c.plan_name.is_not(None), longm.c.member_id.is_not(None))))
        return self.scoped(Member, stmt, scope)

    async def list_eligible(self, scope: BranchScope, *, offset: int, limit: int,
                            search: str | None = None) -> tuple[list, int]:
        """Rows: (Member, diet_plan_name, long_membership, plan_id, plan_tier, last_modified_date)."""
        stmt = self._eligibility_stmt(scope)
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(or_(Member.name.ilike(pattern), Member.phone.ilike(pattern),
                                  Member.registration_id.ilike(pattern)))
        return await self.paginate(stmt.order_by(Member.name, Member.id), offset=offset, limit=limit)

    async def get_eligibility(self, member_id: UUID) -> tuple[str | None, bool]:
        """(latest diet add-on plan name, has ≥90-day membership) for one member."""
        diet = self._latest_diet_addon()
        longm = self._long_membership()
        name = (await self._db.execute(select(diet.c.plan_name).where(diet.c.member_id == member_id))).scalar()
        has_long = (await self._db.execute(select(longm.c.member_id).where(longm.c.member_id == member_id))).first()
        return name, has_long is not None

    # ── members / plans / items ──────────────────────────────────────────
    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    async def get_plan_by_member(self, member_id: UUID, scope: BranchScope) -> DietPlan | None:
        stmt = self.scoped(DietPlan, select(DietPlan).where(DietPlan.member_id == member_id), scope)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_items(self, plan_id: UUID) -> list:
        """Rows: (DietPlanItem, food_name, serving_unit) in insertion order."""
        stmt = (select(DietPlanItem, FoodItem.name, FoodItem.serving_unit)
                .join(FoodItem, FoodItem.id == DietPlanItem.food_item_id)
                .where(DietPlanItem.diet_plan_id == plan_id, DietPlanItem.is_delete.is_(False))
                .order_by(DietPlanItem.created_at, DietPlanItem.id))
        return list((await self._db.execute(stmt)).all())

    async def get_item(self, item_id: UUID, plan_id: UUID) -> DietPlanItem | None:
        stmt = select(DietPlanItem).where(DietPlanItem.id == item_id, DietPlanItem.diet_plan_id == plan_id,
                                          DietPlanItem.is_delete.is_(False))
        return (await self._db.execute(stmt)).scalar_one_or_none()
