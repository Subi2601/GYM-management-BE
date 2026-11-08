"""Pydantic v2 schemas — client assessment (vitals, lifestyle, injuries, static / dynamic movement)."""
from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from shared.schemas.base_schema import TimestampMixin, UUIDSchema

from app.core.enums import Lifestyle
from app.schemas.common import FormSchema

# Dynamic movement screen: the standard tests a trainer watches, each rated.
MovementTest = Literal["OVERHEAD_SQUAT", "LUNGE", "PUSH_UP", "HIP_HINGE", "SINGLE_LEG_BALANCE", "SHOULDER_MOBILITY"]
MovementRating = Literal["GOOD", "FAIR", "POOR"]


class AssessmentInput(FormSchema):
    assessed_on: date
    height_cm: float | None = Field(default=None, ge=50, le=250)
    weight_kg: float | None = Field(default=None, ge=10, le=350)
    body_fat_percent: float | None = Field(default=None, ge=2, le=70)
    waist_cm: float | None = Field(default=None, ge=30, le=250)
    resting_heart_rate: int | None = Field(default=None, ge=30, le=220)
    bp_systolic: int | None = Field(default=None, ge=60, le=260)
    bp_diastolic: int | None = Field(default=None, ge=30, le=160)
    lifestyle: Lifestyle | None = None
    medical_conditions: str | None = Field(default=None, max_length=1000)
    past_injuries: str | None = Field(default=None, max_length=1000)
    surgeries: str | None = Field(default=None, max_length=1000)
    static_notes: str | None = Field(default=None, max_length=2000)            # posture
    movements: dict[MovementTest, MovementRating] = Field(default_factory=dict)
    dynamic_notes: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _bp_pair(self) -> "AssessmentInput":
        if (self.bp_systolic is None) != (self.bp_diastolic is None):
            raise ValueError("Enter both blood pressure numbers (e.g. 120 / 80)")
        if self.bp_systolic is not None and self.bp_systolic <= self.bp_diastolic:
            raise ValueError("The first BP number (systolic) is the higher one")
        return self


class AssessmentResponse(UUIDSchema, TimestampMixin):
    member_id: UUID
    assessed_on: date
    height_cm: float | None = None
    weight_kg: float | None = None
    bmi: float | None = None                   # from height + weight
    body_fat_percent: float | None = None
    waist_cm: float | None = None
    resting_heart_rate: int | None = None
    bp_systolic: int | None = None
    bp_diastolic: int | None = None
    lifestyle: Lifestyle | None = None
    medical_conditions: str | None = None
    past_injuries: str | None = None
    surgeries: str | None = None
    static_notes: str | None = None
    movements: dict[str, str] = {}
    dynamic_notes: str | None = None
    notes: str | None = None
    assessed_by_name: str | None = None
