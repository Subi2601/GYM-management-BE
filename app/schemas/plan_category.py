"""Pydantic v2 schemas — plan categories (owner-managed master)."""
from __future__ import annotations

from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema

from app.schemas.common import FormSchema


class PlanCategoryCreate(FormSchema):
    name: str = Field(min_length=1, max_length=60)


class PlanCategoryUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    is_active: bool | None = None        # inactive categories drop out of billing


class PlanCategoryReorder(FormSchema):
    """Full order, first = first tab."""
    ids: list[UUID] = Field(min_length=1, max_length=100)


class PlanCategoryResponse(TessBaseSchema):
    id: UUID
    name: str
    sort_order: int
    is_active: bool
    plan_count: int            # plans in the selected branch(es)
    active_plan_count: int     # of those, shown for billing
