"""Attendance routes — registration + permission decorators only."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.attendance_controller import AttendanceController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.attendance import (AttendanceMark, AttendanceResponse, DailyAttendanceResponse,
                                    MonthlyAttendanceResponse)

router = APIRouter(prefix="/api/v1/attendance", tags=["attendance"])


@router.get("/daily", response_model=ResponseEnvelope[DailyAttendanceResponse],
            dependencies=[Depends(require_permission("attendance:list"))])
async def daily_attendance(date: date | None = Query(default=None),
                           scope: BranchScope = Depends(get_branch_scope),
                           controller: AttendanceController = Depends()):
    return await controller.daily(scope, date)


@router.get("/monthly", response_model=ResponseEnvelope[MonthlyAttendanceResponse],
            dependencies=[Depends(require_permission("attendance:list"))])
async def monthly_attendance(employee_id: UUID | None = Query(default=None),
                             month: int | None = Query(default=None, ge=1, le=12),
                             year: int | None = Query(default=None, ge=2000, le=2100),
                             scope: BranchScope = Depends(get_branch_scope),
                             controller: AttendanceController = Depends()):
    return await controller.monthly(scope, employee_id, month, year)


@router.post("/mark", response_model=ResponseEnvelope[AttendanceResponse],
             dependencies=[Depends(require_permission("attendance:mark"))])
async def mark_attendance(body: AttendanceMark, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          controller: AttendanceController = Depends()):
    return await controller.mark(body, scope, ctx)


@router.post("/{employee_id}/checkout", response_model=ResponseEnvelope[AttendanceResponse],
             dependencies=[Depends(require_permission("attendance:mark"))])
async def checkout(employee_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                   ctx: RequestContext = Depends(get_current_user), controller: AttendanceController = Depends()):
    return await controller.checkout(employee_id, scope, ctx)
