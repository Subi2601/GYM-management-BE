"""Attendance routes — registration + permission decorators only."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.attendance_controller import AttendanceController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.attendance import (AttendanceLocationUpdate, AttendanceMark, AttendanceQrResponse,
                                    AttendanceResponse, CheckResult, DailyAttendanceResponse, LinkedDeviceResponse,
                                    MemberCheckIn, MemberDailyResponse, MonthlyAttendanceResponse, SessionCheckout)

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


# ── members ──────────────────────────────────────────────────────────────

@router.get("/members/daily", response_model=ResponseEnvelope[MemberDailyResponse],
            dependencies=[Depends(require_permission("attendance:list"))])
async def members_daily(date: date | None = Query(default=None), scope: BranchScope = Depends(get_branch_scope),
                        controller: AttendanceController = Depends()):
    return await controller.members_daily(scope, date)


@router.post("/members/check-in", response_model=ResponseEnvelope[CheckResult],
             dependencies=[Depends(require_permission("attendance:mark"))])
async def member_check_in(body: MemberCheckIn, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          controller: AttendanceController = Depends()):
    return await controller.member_check_in(body.member_id, scope, ctx)


@router.post("/members/{member_id}/check-out", response_model=ResponseEnvelope[CheckResult],
             dependencies=[Depends(require_permission("attendance:mark"))])
async def member_check_out(member_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                           ctx: RequestContext = Depends(get_current_user),
                           controller: AttendanceController = Depends()):
    return await controller.member_check_out(member_id, scope, ctx)


@router.post("/sessions/{session_id}/check-out", response_model=ResponseEnvelope[None],
             dependencies=[Depends(require_permission("attendance:mark"))])
async def close_session(session_id: UUID, body: SessionCheckout = Body(default_factory=SessionCheckout),
                        scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user),
                        controller: AttendanceController = Depends()):
    return await controller.close_session(session_id, body.check_out_time, scope, ctx)


# ── QR posters + linked phones ───────────────────────────────────────────

@router.get("/qr", response_model=ResponseEnvelope[AttendanceQrResponse],
            dependencies=[Depends(require_permission("attendance:qr"))])
async def qr_settings(scope: BranchScope = Depends(get_branch_scope), ctx: RequestContext = Depends(get_current_user),
                      controller: AttendanceController = Depends()):
    return await controller.qr(scope, ctx)


@router.post("/qr/regenerate", response_model=ResponseEnvelope[AttendanceQrResponse],
             dependencies=[Depends(require_permission("attendance:qr"))])
async def regenerate_qr(scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user),
                        controller: AttendanceController = Depends()):
    return await controller.regenerate_qr(scope, ctx)


@router.put("/qr/location", response_model=ResponseEnvelope[AttendanceQrResponse],
            dependencies=[Depends(require_permission("attendance:qr"))])
async def update_location(body: AttendanceLocationUpdate, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          controller: AttendanceController = Depends()):
    return await controller.update_location(body, scope, ctx)


@router.get("/qr/devices", response_model=ResponseEnvelope[list[LinkedDeviceResponse]],
            dependencies=[Depends(require_permission("attendance:qr"))])
async def linked_devices(scope: BranchScope = Depends(get_branch_scope),
                         controller: AttendanceController = Depends()):
    return await controller.devices(scope)


@router.delete("/qr/devices/{device_id}", response_model=ResponseEnvelope[None],
               dependencies=[Depends(require_permission("attendance:qr"))])
async def unlink_device(device_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                        ctx: RequestContext = Depends(get_current_user),
                        controller: AttendanceController = Depends()):
    return await controller.unlink_device(device_id, scope, ctx)


@router.post("/{employee_id}/checkout", response_model=ResponseEnvelope[AttendanceResponse],
             dependencies=[Depends(require_permission("attendance:mark"))])
async def checkout(employee_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                   ctx: RequestContext = Depends(get_current_user), controller: AttendanceController = Depends()):
    return await controller.checkout(employee_id, scope, ctx)
