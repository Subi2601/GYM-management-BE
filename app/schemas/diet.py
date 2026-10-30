"""Pydantic v2 schemas — diet plans."""
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import DietCategory, DietTier, Gender, MealTime
from app.schemas.common import FormSchema

# Activity multipliers offered by the builder (sedentary → extra active).
ActivityLevel = Literal[1.2, 1.375, 1.55, 1.725, 1.9]


class DietPlanUpsert(FormSchema):
    tier: DietTier
    category: DietCategory = DietCategory.VEG
    weight: float = Field(ge=20, le=400)        # kg
    height: float = Field(ge=50, le=300)        # cm
    age: int = Field(ge=10, le=120)
    activity_level: ActivityLevel = 1.2
    notes: str | None = Field(default=None, max_length=2000)


class DietPlanItemCreate(FormSchema):
    food_item_id: UUID
    meal_time: MealTime
    quantity: float = Field(default=100, gt=0, le=5000)


class EligibleMemberResponse(TessBaseSchema):
    member_id: UUID
    registration_id: str
    name: str
    phone: str
    gender: Gender
    eligible_tier: DietTier
    has_plan: bool
    plan_id: UUID | None = None
    plan_tier: DietTier | None = None
    last_modified_date: date | None = None


class MacroTotals(TessBaseSchema):
    calories: float
    protein: float
    carbs: float
    fats: float


class DietPlanItemResponse(TessBaseSchema):
    id: UUID
    food_item_id: UUID
    food_name: str
    quantity: float
    serving_unit: str
    calories: float
    protein: float
    carbs: float
    fats: float


class MealResponse(TessBaseSchema):
    meal_time: MealTime
    items: list[DietPlanItemResponse]
    totals: MacroTotals


class DietPlanResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    member_id: UUID
    member_name: str
    registration_id: str
    tier: DietTier
    category: DietCategory
    weight: float | None = None
    height: float | None = None
    age: int | None = None
    activity_level: float
    bmi: float | None = None
    bmi_status: str | None = None
    bmr: float | None = None
    tdee: float | None = None
    target_calories: float | None = None
    target_protein: float | None = None
    target_carbs: float | None = None
    target_fats: float | None = None
    modification_count: int
    monthly_update_limit: int | None = None     # None = unlimited
    items_editable: bool                        # False for BASIC
    last_modified_date: date | None = None
    notes: str | None = None
    meals: list[MealResponse]
    totals: MacroTotals                         # current assigned calories / macros


class ShareTextResponse(TessBaseSchema):
    model_config = ConfigDict(str_strip_whitespace=False)   # keep the message byte-identical

    phone: str
    text: str
    whatsapp_url: str
