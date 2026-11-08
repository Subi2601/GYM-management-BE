"""Gym settings — values the owner can change for every branch (trial class, renewal windows, staff late grace).

Other services read them through `SettingsService.values(org_id)` instead of hard-coded constants.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.repositories.settings_repository import SettingsRepository

FIELDS = ("trial_enabled", "trial_days", "trial_fee", "renewal_due_days", "renewal_overdue_days",
          "late_grace_minutes", "half_day_after_minutes", "absent_alert_days", "freeze_enabled", "freeze_max_days", "freeze_max_times",
          "transfer_enabled", "transfer_within_days", "refund_within_days", "refund_deduction_percent")


@dataclass(frozen=True)
class GymSettings:
    trial_enabled: bool = True
    trial_days: int = 3
    trial_fee: Decimal = Decimal(0)
    renewal_due_days: int = 7
    renewal_overdue_days: int = 30
    late_grace_minutes: int = 10
    half_day_after_minutes: int = 30       # 0 = never a half day for coming late
    absent_alert_days: int = 7
    freeze_enabled: bool = True
    freeze_max_days: int = 30            # 0 = only members given their own allowance
    freeze_max_times: int = 2
    transfer_enabled: bool = True
    transfer_within_days: int = 30
    refund_within_days: int = 7
    refund_deduction_percent: Decimal = Decimal(10)
    # Read-only here (the gym's identity): shown as Gym ID; member ids use member_id_prefix or the code.
    gym_code: str = ""
    member_id_prefix: str = "SG"


DEFAULTS = GymSettings()


class SettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = SettingsRepository(db)

    @staticmethod
    def _out(org: Organization) -> GymSettings:
        return GymSettings(**{f: getattr(org, f) for f in FIELDS}, gym_code=org.code,
                           member_id_prefix=org.member_id_prefix or org.code)

    async def values(self, organization_id: UUID) -> GymSettings:
        org = await self._repo.get_org(organization_id)
        return self._out(org) if org is not None else DEFAULTS

    async def get(self, organization_id: UUID) -> dict:
        return vars(await self.values(organization_id))

    async def update(self, organization_id: UUID, data, actor: RequestContext) -> dict:
        org = await self._repo.get_org(organization_id)
        if org is None:
            raise NotFoundError("Gym")
        grace = data.late_grace_minutes if data.late_grace_minutes is not None else org.late_grace_minutes
        half = data.half_day_after_minutes if data.half_day_after_minutes is not None else org.half_day_after_minutes
        if half and half <= grace:
            raise BadRequestError(f"Half day must start after the late grace ({grace} min). Set more than {grace}, "
                                  "or 0 for no half day")
        for field in FIELDS:
            if field in data.model_fields_set and getattr(data, field) is not None:
                value = getattr(data, field)
                setattr(org, field, Decimal(str(value)) if isinstance(value, float) else value)
        org.updated_by = actor.user_id
        await self._repo.commit()
        return vars(self._out(org))
