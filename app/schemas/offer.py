"""Pydantic v2 schemas — offers (discount master)."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import Field, model_validator
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.schemas.common import FormSchema


class OfferCreate(FormSchema):
    """An offer gives any mix of: % off, extra membership time, a free item — at least one of them."""
    name: str = Field(min_length=1, max_length=80)
    discount_percent: float = Field(default=0, ge=0, le=100)
    extra_months: int = Field(default=0, ge=0, le=24)
    extra_days: int = Field(default=0, ge=0, le=365)
    free_item: str | None = Field(default=None, max_length=120)      # "Protein shaker", "Gym T-shirt"
    valid_from: date | None = None
    valid_to: date | None = None
    description: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    # Plan categories the offer applies to; empty = every plan.
    category_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _gives_something(self) -> "OfferCreate":
        if not (self.discount_percent or self.extra_months or self.extra_days or (self.free_item or "").strip()):
            raise ValueError("An offer needs a % off, extra time or a free item")
        return self


class OfferUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    discount_percent: float | None = Field(default=None, ge=0, le=100)
    extra_months: int | None = Field(default=None, ge=0, le=24)
    extra_days: int | None = Field(default=None, ge=0, le=365)
    free_item: str | None = Field(default=None, max_length=120)
    valid_from: date | None = None
    valid_to: date | None = None
    description: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    category_ids: list[UUID] | None = Field(default=None, max_length=100)


class OfferStatusUpdate(FormSchema):
    is_active: bool


class OfferResponse(UUIDSchema, TimestampMixin):
    name: str
    discount_percent: float
    extra_months: int = 0
    extra_days: int = 0
    free_item: str | None = None
    summary: str                      # "10% off · +1 month · Free protein shaker"
    valid_from: date | None = None
    valid_to: date | None = None
    description: str | None = None
    is_active: bool
    # Derived: switched on AND today is inside the date window — what billing screens offer.
    available: bool
    category_ids: list[UUID] = []     # empty = applies to every plan


class OfferCounts(TessBaseSchema):
    """Row count per list tab (GET /offers/counts)."""
    active: int
    inactive: int
    all: int
