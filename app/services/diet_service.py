"""Diet plan business logic — eligibility tiers, BMI/BMR/TDEE/macro maths, modification limits, meals."""
from __future__ import annotations

from datetime import date
from urllib.parse import quote
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import DietTier, Gender, MealTime
from app.core.scope import BranchScope
from app.models.diet import DietPlan, DietPlanItem
from app.models.member import Member
from app.repositories.diet_repository import DietRepository
from app.repositories.food_repository import FoodRepository

TIER_RANK = {DietTier.BASIC: 1, DietTier.STANDARD: 2, DietTier.PREMIUM: 3}
STANDARD_MONTHLY_LIMIT = 2
# Macro split — 40% protein / 30% carbs / 30% fats (kcal per gram: 4 / 4 / 9).
PROTEIN_PCT, CARBS_PCT, FATS_PCT = 0.40, 0.30, 0.30
_URI_SAFE = "-_.!~*'()"   # characters JavaScript's encodeURIComponent leaves as-is


# ── pure calculations ────────────────────────────────────────────────────
def tier_from_eligibility(diet_plan_name: str | None, long_membership: bool) -> DietTier | None:
    """Latest DIET add-on decides the tier by plan name; else a ≥90-day membership gives BASIC."""
    if diet_plan_name is not None:
        name = diet_plan_name.lower()
        if "premium" in name:
            return DietTier.PREMIUM
        if "standard" in name:
            return DietTier.STANDARD
        return DietTier.BASIC
    return DietTier.BASIC if long_membership else None


def calculate_bmi(weight: float, height_cm: float) -> float:
    meters = height_cm / 100
    return weight / (meters * meters)


def bmi_status(bmi: float | None) -> str | None:
    if bmi is None:
        return None
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


def calculate_bmr(weight: float, height_cm: float, age: int, gender: Gender) -> float:
    """Mifflin-St Jeor."""
    base = 10 * weight + 6.25 * height_cm - 5 * age
    return base + 5 if gender == Gender.MALE else base - 161


def calculate_targets(weight: float, height: float, age: int, activity: float, gender: Gender) -> dict:
    bmi = calculate_bmi(weight, height)
    bmr = calculate_bmr(weight, height, age, gender)
    tdee = bmr * activity
    return {
        "bmi": round(bmi, 1), "bmr": float(round(bmr)), "tdee": float(round(tdee)),
        "target_calories": float(round(tdee)),
        "target_protein": float(round(tdee * PROTEIN_PCT / 4)),
        "target_carbs": float(round(tdee * CARBS_PCT / 4)),
        "target_fats": float(round(tdee * FATS_PCT / 9)),
    }


def monthly_limit(tier: DietTier) -> int | None:
    return STANDARD_MONTHLY_LIMIT if tier == DietTier.STANDARD else None


def _js_num(value: float | None) -> str:
    """Render a number the way JavaScript template strings do (165.0 → '165')."""
    if value is None:
        return "0"
    value = round(float(value), 1)
    return str(int(value)) if value.is_integer() else str(value)


def _same_month(a: date | None, b: date) -> bool:
    return a is not None and (a.year, a.month) == (b.year, b.month)


class DietService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = DietRepository(db)
        self._foods = FoodRepository(db)

    # ── output builders ──────────────────────────────────────────────────
    @staticmethod
    def _totals(items: list[dict]) -> dict:
        return {k: round(sum(i[k] for i in items), 1) for k in ("calories", "protein", "carbs", "fats")}

    async def _plan_out(self, plan: DietPlan, member: Member) -> dict:
        rows = await self._repo.list_items(plan.id)
        by_meal: dict[MealTime, list[dict]] = {m: [] for m in MealTime}
        for item, food_name, serving_unit in rows:
            by_meal[MealTime(item.meal_time)].append({
                "id": item.id, "food_item_id": item.food_item_id, "food_name": food_name,
                "quantity": item.quantity, "serving_unit": serving_unit,
                "calories": round(item.total_calories, 1), "protein": round(item.total_protein, 1),
                "carbs": round(item.total_carbs, 1), "fats": round(item.total_fats, 1),
            })
        meals = [{"meal_time": m, "items": items, "totals": self._totals(items)} for m, items in by_meal.items()]
        tier = DietTier(plan.tier)
        return {
            "id": plan.id, "branch_id": plan.branch_id, "member_id": member.id, "member_name": member.name,
            "registration_id": member.registration_id, "tier": tier, "category": plan.category,
            "weight": plan.weight, "height": plan.height, "age": plan.age, "activity_level": plan.activity_level,
            "bmi": plan.bmi, "bmi_status": bmi_status(plan.bmi), "bmr": plan.bmr, "tdee": plan.tdee,
            "target_calories": plan.target_calories, "target_protein": plan.target_protein,
            "target_carbs": plan.target_carbs, "target_fats": plan.target_fats,
            "modification_count": plan.modification_count, "monthly_update_limit": monthly_limit(tier),
            "items_editable": tier != DietTier.BASIC, "last_modified_date": plan.last_modified_date,
            "notes": plan.notes, "meals": meals,
            "totals": self._totals([i for m in meals for i in m["items"]]),
            "created_at": plan.created_at, "updated_at": plan.updated_at,
        }

    # ── helpers ──────────────────────────────────────────────────────────
    async def _member(self, member_id: UUID, scope: BranchScope) -> Member:
        member = await self._repo.get_member(member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        return member

    async def _plan_and_member(self, member_id: UUID, scope: BranchScope) -> tuple[DietPlan, Member]:
        member = await self._member(member_id, scope)
        plan = await self._repo.get_plan_by_member(member_id, scope)
        if plan is None:
            raise NotFoundError("Diet plan")
        return plan, member

    async def _editable_plan(self, member_id: UUID, scope: BranchScope) -> tuple[DietPlan, Member]:
        scope.require_branch()
        member = await self._member(member_id, scope)
        plan = await self._repo.get_plan_by_member(member_id, scope)
        if plan is None:
            raise BadRequestError("Configure the diet plan first")
        if plan.tier == DietTier.BASIC:
            raise BadRequestError("Basic plans cannot be modified. Upgrade to Standard or Premium.")
        return plan, member

    # ── queries ──────────────────────────────────────────────────────────
    async def list_eligible(self, scope: BranchScope, *, offset: int, limit: int,
                            search: str | None) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_eligible(scope, offset=offset, limit=limit, search=search)
        out = []
        for m, diet_name, long_membership, plan_id, plan_tier, last_modified in rows:
            out.append({
                "member_id": m.id, "registration_id": m.registration_id, "name": m.name, "phone": m.phone,
                "gender": m.gender, "eligible_tier": tier_from_eligibility(diet_name, long_membership),
                "has_plan": plan_id is not None, "plan_id": plan_id, "plan_tier": plan_tier,
                "last_modified_date": last_modified,
            })
        return out, total

    async def get_plan(self, member_id: UUID, scope: BranchScope) -> dict:
        plan, member = await self._plan_and_member(member_id, scope)
        return await self._plan_out(plan, member)

    async def share_text(self, member_id: UUID, scope: BranchScope) -> dict:
        """WhatsApp message, identical to the original builder's shareWhatsApp()."""
        plan, member = await self._plan_and_member(member_id, scope)
        data = await self._plan_out(plan, member)
        text ="*STAG FITNESS - DIET PLAN*\n"
        text += f"*Member:* {data['member_name']}\n"
        text += f"*Tier:* {data['tier'].value}\n\n"
        text += "*Daily Targets:*\n"
        text += f"- Calories: {_js_num(data['target_calories'])} kcal\n"
        text += f"- Protein: {_js_num(data['target_protein'])}g\n"
        text += f"- Carbs: {_js_num(data['target_carbs'])}g\n"
        text += f"- Fats: {_js_num(data['target_fats'])}g\n\n"
        text += "*Meal Schedule:*\n"
        for meal in data["meals"]:
            if meal["items"]:
                names = ", ".join(i["food_name"] for i in meal["items"])
                text += f"*{meal['meal_time'].value}:* {names} ({_js_num(meal['totals']['calories'])} kcal)\n"
        phone = member.phone or ""
        if len(phone) == 10:
            phone = "91" + phone
        url = f"https://api.whatsapp.com/send?phone={phone}&text={quote(text, safe=_URI_SAFE)}"
        return {"phone": phone, "text": text, "whatsapp_url": url}

    # ── commands ─────────────────────────────────────────────────────────
    async def upsert_plan(self, member_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        member = await self._member(member_id, scope)
        eligible = tier_from_eligibility(*await self._repo.get_eligibility(member.id))
        if eligible is None:
            raise BadRequestError("Member is not eligible for a diet plan")
        if TIER_RANK[data.tier] > TIER_RANK[eligible]:
            raise BadRequestError(f"Member is only eligible for the {eligible.value} diet tier")

        today = timeutil.today()
        plan = await self._repo.get_plan_by_member(member.id, scope)
        is_new = plan is None
        if is_new:
            plan = DietPlan(organization_id=member.organization_id, branch_id=member.branch_id,
                            member_id=member.id, modification_count=0, created_by=actor.user_id)
        else:
            plan.updated_by = actor.user_id
        if not _same_month(plan.last_modified_date, today):
            plan.modification_count = 0          # monthly allowance resets when the month changes
        limit = monthly_limit(data.tier)
        if limit is not None and plan.modification_count >= limit:
            raise BadRequestError("Standard plan modification limit reached for this month")

        plan.tier = data.tier
        plan.category = data.category
        plan.weight, plan.height, plan.age = data.weight, data.height, data.age
        plan.activity_level = float(data.activity_level)
        plan.notes = data.notes
        for key, value in calculate_targets(data.weight, data.height, data.age, plan.activity_level,
                                            Gender(member.gender)).items():
            setattr(plan, key, value)
        plan.modification_count += 1
        plan.last_modified_date = today
        if is_new:
            await self._repo.add(plan)
        await self._repo.commit()
        await self._repo.refresh(plan)
        return await self._plan_out(plan, member)

    async def add_item(self, member_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        plan, member = await self._editable_plan(member_id, scope)
        food = await self._foods.get_visible(data.food_item_id, scope.organization_id)
        if food is None:
            raise NotFoundError("Food item")
        factor = data.quantity / 100
        await self._repo.add(DietPlanItem(
            organization_id=plan.organization_id, branch_id=plan.branch_id, diet_plan_id=plan.id,
            food_item_id=food.id, meal_time=data.meal_time, quantity=data.quantity,
            total_calories=round(food.calories * factor, 2), total_protein=round(food.protein * factor, 2),
            total_carbs=round(food.carbs * factor, 2), total_fats=round(food.fats * factor, 2),
            created_by=actor.user_id,
        ))
        await self._repo.commit()
        await self._repo.refresh(plan)
        return await self._plan_out(plan, member)

    async def remove_item(self, member_id: UUID, item_id: UUID, scope: BranchScope) -> dict:
        plan, member = await self._editable_plan(member_id, scope)
        item = await self._repo.get_item(item_id, plan.id)
        if item is None:
            raise NotFoundError("Diet plan item")
        await self._repo.delete(item)
        await self._repo.commit()
        await self._repo.refresh(plan)
        return await self._plan_out(plan, member)
