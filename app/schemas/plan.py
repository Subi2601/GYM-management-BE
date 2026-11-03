"""Pydantic v2 schemas — plans."""
from __future__ import annotations

from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import PlanServiceType, PlanType
from app.schemas.common import FormSchema


class PlanCreate(FormSchema):
    name: str = Field(min_length=1, max_length=120)
    type: PlanType = PlanType.MEMBERSHIP
    service_type: PlanServiceType = PlanServiceType.GENERAL
    duration_days: int = Field(ge=1, le=3650)
    price: float = Field(ge=0, le=10_000_000)
    total_sessions: int = Field(default=0, ge=0, le=1000)
    description: str | None = Field(default=None, max_length=2000)


class PlanUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: PlanType | None = None
    service_type: PlanServiceType | None = None
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    price: float | None = Field(default=None, ge=0, le=10_000_000)
    total_sessions: int | None = Field(default=None, ge=0, le=1000)
    description: str | None = Field(default=None, max_length=2000)


class PlanResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    name: str
    type: PlanType
    service_type: PlanServiceType
    duration_days: int
    price: float
    total_sessions: int
    description: str | None = None


class PlanCounts(TessBaseSchema):
    """Row count per list tab (GET /plans/counts): all / MEMBERSHIP / ADD_ON / CUSTOM."""
    all: int
    membership: int
    addon: int
    custom: int
