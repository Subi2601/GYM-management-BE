"""Pydantic v2 schemas — food catalogue."""
from __future__ import annotations

from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TimestampMixin, UUIDSchema

from app.core.enums import FoodCategory
from app.schemas.common import FormSchema


class FoodItemCreate(FormSchema):
    """Nutrition values are per 100 g (or per serving unit)."""
    name: str = Field(min_length=1, max_length=120)
    category: FoodCategory = FoodCategory.VEG
    calories: float = Field(ge=0, le=2000)
    protein: float = Field(default=0, ge=0, le=200)
    carbs: float = Field(default=0, ge=0, le=200)
    fats: float = Field(default=0, ge=0, le=200)
    fiber: float | None = Field(default=None, ge=0, le=200)
    serving_unit: str = Field(default="grams", min_length=1, max_length=30)
    nutritional_benefits: str | None = Field(default=None, max_length=300)
    image_url: str | None = Field(default=None, max_length=300)


class FoodItemResponse(UUIDSchema, TimestampMixin):
    organization_id: UUID | None = None
    is_platform: bool                   # True = shared platform catalogue (read-only to gyms)
    name: str
    category: FoodCategory
    calories: float
    protein: float
    carbs: float
    fats: float
    fiber: float | None = None
    serving_unit: str
    nutritional_benefits: str | None = None
    image_url: str | None = None
