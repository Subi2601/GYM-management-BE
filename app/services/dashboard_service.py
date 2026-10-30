"""Dashboard KPIs + real 6-month growth series (replaces the old hard-coded chart)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.scope import BranchScope
from app.repositories.dashboard_repository import DashboardRepository
from app.services.payment_service import add_months

EXPIRING_WEEK_DAYS = 7
GROWTH_MONTHS = 6


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = DashboardRepository(db)

    async def summary(self, scope: BranchScope) -> dict:
        today = timeutil.today()
        total_revenue, today_revenue = await self._repo.revenue(scope, today)
        first = add_months(date(today.year, today.month, 1), -(GROWTH_MONTHS - 1))
        joins = await self._repo.new_members_by_month(scope, first)
        revenue = await self._repo.revenue_by_month(scope, first)
        growth = []
        for i in range(GROWTH_MONTHS):
            month = add_months(first, i)
            growth.append({"month": f"{calendar.month_abbr[month.month]} {month.year}",
                           "new_members": joins.get(month, 0), "revenue": revenue.get(month) or Decimal(0)})
        return {
            "total_members": await self._repo.count_members(scope),
            "active_members": await self._repo.count_memberships_ending(scope, today, None),
            "total_revenue": total_revenue,
            "today_revenue": today_revenue,
            "expiring_this_week": await self._repo.count_memberships_ending(
                scope, today, today + timedelta(days=EXPIRING_WEEK_DAYS)),
            "open_leads": await self._repo.count_open_leads(scope),
            "growth": growth,
        }
