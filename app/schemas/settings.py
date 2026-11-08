"""Pydantic v2 schemas — gym settings."""
from __future__ import annotations

from pydantic import Field
from shared.schemas.base_schema import TessBaseSchema

from app.schemas.common import FormSchema


class GymSettingsResponse(TessBaseSchema):
    gym_code: str                             # Gym ID (set when the gym is onboarded, read-only)
    member_id_prefix: str
    trial_enabled: bool
    trial_days: int
    trial_fee: float
    renewal_due_days: int
    renewal_overdue_days: int
    late_grace_minutes: int
    half_day_after_minutes: int
    absent_alert_days: int
    freeze_enabled: bool
    freeze_max_days: int
    freeze_max_times: int
    transfer_enabled: bool
    transfer_within_days: int
    refund_within_days: int
    refund_deduction_percent: float


class GymSettingsUpdate(FormSchema):
    trial_enabled: bool | None = None
    trial_days: int | None = Field(default=None, ge=1, le=30)
    trial_fee: float | None = Field(default=None, ge=0, le=100000)
    renewal_due_days: int | None = Field(default=None, ge=1, le=60)
    renewal_overdue_days: int | None = Field(default=None, ge=1, le=365)
    late_grace_minutes: int | None = Field(default=None, ge=0, le=120)
    half_day_after_minutes: int | None = Field(default=None, ge=0, le=480)
    absent_alert_days: int | None = Field(default=None, ge=2, le=60)
    freeze_enabled: bool | None = None
    freeze_max_days: int | None = Field(default=None, ge=0, le=365)
    freeze_max_times: int | None = Field(default=None, ge=1, le=12)
    transfer_enabled: bool | None = None
    transfer_within_days: int | None = Field(default=None, ge=1, le=365)
    refund_within_days: int | None = Field(default=None, ge=0, le=365)
    refund_deduction_percent: float | None = Field(default=None, ge=0, le=100)


class DeskSettings(TessBaseSchema):
    """What the desk screens need (Leads trial offer, Renewals / Members windows) — any signed-in account."""
    gym_code: str
    trial_enabled: bool
    trial_days: int
    trial_fee: float
    renewal_due_days: int
    renewal_overdue_days: int
    absent_alert_days: int
