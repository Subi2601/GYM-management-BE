"""Pydantic v2 schemas — plans."""
from __future__ import annotations

from uuid import UUID

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema, TimestampMixin, UUIDSchema

from app.core.enums import PlanServiceType, PlanType
from app.schemas.common import FormSchema


class PlanCreate(FormSchema):
    name: str = Field(min_length=1, max_length=120)
    category_id: UUID
    type: PlanType = PlanType.MEMBERSHIP
    service_type: PlanServiceType = PlanServiceType.GENERAL
    # Bill by calendar months (memberships) OR by days (PT validity, custom). One of the two is required.
    duration_months: int | None = Field(default=None, ge=1, le=60)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    price: float = Field(ge=0, le=10_000_000)
    total_sessions: int = Field(default=0, ge=0, le=1000)
    group_size: int = Field(default=1, ge=1, le=50)
    free_members: int = Field(default=0, ge=0, le=49)
    id_check: str | None = Field(default=None, max_length=60)
    all_branches: bool = False
    # Days after the start date a member on this plan may still upgrade (0 = never). Empty = default by duration.
    upgrade_window_days: int | None = Field(default=None, ge=0, le=3650)
    is_active: bool = True
    description: str | None = Field(default=None, max_length=2000)
    # Money back on cancel; within these days of use (empty = the gym's refund days).
    refundable: bool = False
    refund_window_days: int | None = Field(default=None, ge=0, le=3650)


class PlanUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category_id: UUID | None = None
    type: PlanType | None = None
    service_type: PlanServiceType | None = None
    duration_months: int | None = Field(default=None, ge=1, le=60)
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    price: float | None = Field(default=None, ge=0, le=10_000_000)
    total_sessions: int | None = Field(default=None, ge=0, le=1000)
    group_size: int | None = Field(default=None, ge=1, le=50)
    free_members: int | None = Field(default=None, ge=0, le=49)
    id_check: str | None = Field(default=None, max_length=60)
    all_branches: bool | None = None
    upgrade_window_days: int | None = Field(default=None, ge=0, le=3650)
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=2000)
    refundable: bool | None = None
    refund_window_days: int | None = Field(default=None, ge=0, le=3650)


class PlanResponse(UUIDSchema, TimestampMixin):
    branch_id: UUID
    name: str
    category_id: UUID
    category_name: str
    type: PlanType
    service_type: PlanServiceType
    duration_months: int | None = None     # set → calendar months; NULL → duration_days
    duration_days: int
    price: float
    total_sessions: int
    group_size: int
    free_members: int
    id_check: str | None = None
    all_branches: bool
    upgrade_window_days: int               # 0 = no upgrade from this plan
    is_active: bool                        # False = inactive: not offered in billing
    description: str | None = None
    refundable: bool = False
    refund_window_days: int | None = None  # None = the gym's refund days


class PlanCounts(TessBaseSchema):
    """Row count per list tab (GET /plans/counts): all / active / inactive, and per type."""
    all: int
    active: int
    inactive: int
    membership: int
    addon: int
    custom: int
