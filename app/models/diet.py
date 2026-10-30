"""Food catalogue and per-member diet plans."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DietCategory, DietTier, FoodCategory, MealTime
from app.models.base import BaseModel, BranchScopedMixin


class FoodItem(BaseModel):
    """Nutrition values are per 100 g (or per serving unit). organization_id NULL = platform catalogue."""
    __tablename__ = "diet_food_items"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_organizations.id", ondelete="CASCADE"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[FoodCategory] = mapped_column(Enum(FoodCategory, name="food_category"), nullable=False)
    calories: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    protein: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    carbs: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    fats: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    fiber: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    nutritional_benefits: Mapped[str | None] = mapped_column(String(300), nullable=True)
    serving_unit: Mapped[str] = mapped_column(String(30), nullable=False, default="grams")


class DietPlan(BranchScopedMixin, BaseModel):
    __tablename__ = "diet_plans"
    __table_args__ = (UniqueConstraint("member_id", name="uq_diet_plans_member"),)

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("member_members.id", ondelete="CASCADE"), nullable=False,
    )
    tier: Mapped[DietTier] = mapped_column(Enum(DietTier, name="diet_tier"), nullable=False)
    category: Mapped[DietCategory] = mapped_column(
        Enum(DietCategory, name="diet_category"), nullable=False,
        default=DietCategory.VEG, server_default=text("'VEG'"),
    )
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)        # kg
    height: Mapped[float | None] = mapped_column(Float, nullable=True)        # cm
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_level: Mapped[float] = mapped_column(Float, nullable=False, default=1.2)
    bmi: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr: Mapped[float | None] = mapped_column(Float, nullable=True)
    tdee: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_calories: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_protein: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_carbs: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_fats: Mapped[float | None] = mapped_column(Float, nullable=True)
    modification_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_modified_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class DietPlanItem(BranchScopedMixin, BaseModel):
    __tablename__ = "diet_plan_items"

    diet_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diet_plans.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    food_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("diet_food_items.id", ondelete="RESTRICT"), nullable=False,
    )
    meal_time: Mapped[MealTime] = mapped_column(
        Enum(MealTime, name="meal_time", values_callable=lambda e: [m.value for m in e]), nullable=False,
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=100)  # grams / units
    total_calories: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    total_protein: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    total_carbs: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    total_fats: Mapped[float] = mapped_column(Float, nullable=False, default=0)
