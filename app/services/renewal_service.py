"""Renewals business logic — who to remind, and recording that a reminder went out (sent by the desk on WhatsApp)."""
from __future__ import annotations

from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.scope import BranchScope
from app.models.base import utcnow
from app.models.billing import Subscription
from app.repositories.renewal_repository import RenewalRepository
from app.services.settings_service import SettingsService


class RenewalService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = RenewalRepository(db)
        self._settings = SettingsService(db)

    async def _windows(self, scope: BranchScope, within: int | None) -> tuple[int, int]:
        """(due window, overdue window): `within` from the screen, else the gym's renewal days."""
        s = await self._settings.values(scope.organization_id)
        return within or s.renewal_due_days, s.renewal_overdue_days

    @staticmethod
    def row_out(s: Subscription, name: str, registration_id: str, phone: str, plan_name: str) -> dict:
        return {"subscription_id": s.id, "member_id": s.member_id, "member_name": name,
                "registration_id": registration_id, "phone": phone, "plan_name": plan_name, "end_date": s.end_date,
                "days_left": (s.end_date - timeutil.today()).days, "reminded_at": s.reminded_at,
                "reminder_count": s.reminder_count}

    async def list_renewals(self, scope: BranchScope, *, offset: int, limit: int, within: int | None, tab: str,
                            search: str | None, sort_by: str | None, sort_dir: str) -> tuple[list[dict], int]:
        due, overdue = await self._windows(scope, within)
        rows, total = await self._repo.list_renewals(scope, offset=offset, limit=limit, today=timeutil.today(),
                                                     within=due, overdue_days=overdue, tab=tab, search=search,
                                                     sort_by=sort_by, sort_dir=sort_dir)
        return [self.row_out(*r) for r in rows], total

    async def tab_counts(self, scope: BranchScope, within: int | None) -> dict:
        due, overdue = await self._windows(scope, within)
        return await self._repo.tab_counts(scope, timeutil.today(), due, overdue)

    async def mark_reminded(self, subscription_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        """The desk opened WhatsApp with the reminder — stamp it so the list shows when / how often."""
        scope.require_branch()
        row = await self._repo.get_row(subscription_id, scope)
        if row is None:
            raise NotFoundError("Membership")
        sub = row[0]
        sub.reminded_at = utcnow()
        sub.reminder_count += 1
        sub.updated_by = actor.user_id
        await self._repo.commit()
        return self.row_out(*row)
