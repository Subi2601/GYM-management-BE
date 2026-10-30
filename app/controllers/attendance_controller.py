"""Attendance request/response handling — no business logic (AttendanceService)."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.attendance import (AttendanceMark, AttendanceResponse, DailyAttendanceResponse,
                                    MonthlyAttendanceResponse)
from app.services.attendance_service import AttendanceService


class AttendanceController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = AttendanceService(db)

    async def daily(self, scope: BranchScope, day: date | None) -> ResponseEnvelope[DailyAttendanceResponse]:
        return ResponseEnvelope.ok(DailyAttendanceResponse(**await self._service.daily(scope, day)))

    async def monthly(self, scope: BranchScope, employee_id: UUID | None, month: int | None,
                      year: int | None) -> ResponseEnvelope[MonthlyAttendanceResponse]:
        data = await self._service.monthly(scope, employee_id, month, year)
        return ResponseEnvelope.ok(MonthlyAttendanceResponse(**data))

    async def mark(self, body: AttendanceMark, scope: BranchScope,
                   ctx: RequestContext) -> ResponseEnvelope[AttendanceResponse]:
        data = await self._service.mark(body, scope, ctx)
        return ResponseEnvelope.ok(AttendanceResponse(**data), message="Attendance marked")

    async def checkout(self, employee_id: UUID, scope: BranchScope,
                       ctx: RequestContext) -> ResponseEnvelope[AttendanceResponse]:
        data = await self._service.checkout(employee_id, scope, ctx)
        return ResponseEnvelope.ok(AttendanceResponse(**data), message="Checked out")
