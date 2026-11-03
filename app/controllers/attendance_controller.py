"""Attendance request/response handling — no business logic (AttendanceService, CheckinService)."""
from __future__ import annotations

from datetime import date, time
from uuid import UUID

from fastapi import Depends, Request, Response
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.attendance import (AttendanceLocationUpdate, AttendanceMark, AttendanceQrResponse,
                                    AttendanceResponse, CheckinInfoResponse, CheckinPerson, CheckinScan,
                                    CheckinVerify, CheckResult, DailyAttendanceResponse, LinkedDeviceResponse,
                                    MemberDailyResponse, MonthlyAttendanceResponse)
from app.services.attendance_service import AttendanceService, clock
from app.services.checkin_service import CheckinService

DEVICE_COOKIE_NAME = "stag_device"
DEVICE_COOKIE_PATH = "/api/v1/public/checkin"
DEVICE_COOKIE_MAX_AGE = 400 * 24 * 3600     # browsers cap cookie lifetime at ~400 days


def _result_message(r: dict) -> str:
    """Toast / scan-screen text for a check-in or check-out."""
    if r["direction"] == "IN":
        return f"{r['name']} checked in at {clock(r['time'])}" + (" (late)" if r["late"] else "")
    minutes = r["duration_minutes"] or 0
    return f"{r['name']} checked out at {clock(r['time'])} after {minutes // 60}h {minutes % 60}m"


class AttendanceController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = AttendanceService(db)
        self._checkin = CheckinService(db)

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

    # ── members ──────────────────────────────────────────────────────────
    async def members_daily(self, scope: BranchScope, day: date | None) -> ResponseEnvelope[MemberDailyResponse]:
        return ResponseEnvelope.ok(MemberDailyResponse(**await self._service.members_daily(scope, day)))

    async def member_check_in(self, member_id: UUID, scope: BranchScope,
                              ctx: RequestContext) -> ResponseEnvelope[CheckResult]:
        data = await self._service.member_check_in(member_id, scope, ctx)
        return ResponseEnvelope.ok(CheckResult(**data), message=_result_message(data))

    async def member_check_out(self, member_id: UUID, scope: BranchScope,
                               ctx: RequestContext) -> ResponseEnvelope[CheckResult]:
        data = await self._service.member_check_out(member_id, scope, ctx)
        return ResponseEnvelope.ok(CheckResult(**data), message=_result_message(data))

    async def close_session(self, session_id: UUID, at: time | None, scope: BranchScope,
                            ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._service.close_session(session_id, at, scope, ctx)
        return ResponseEnvelope.ok(None, message="Visit checked out")

    # ── QR posters + linked phones ───────────────────────────────────────
    async def qr(self, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[AttendanceQrResponse]:
        return ResponseEnvelope.ok(AttendanceQrResponse(**await self._checkin.qr_settings(scope, ctx)))

    async def regenerate_qr(self, scope: BranchScope, ctx: RequestContext) -> ResponseEnvelope[AttendanceQrResponse]:
        data = await self._checkin.regenerate(scope, ctx)
        return ResponseEnvelope.ok(AttendanceQrResponse(**data),
                                   message="New QR codes created. Print them; the old posters no longer work")

    async def update_location(self, body: AttendanceLocationUpdate, scope: BranchScope,
                              ctx: RequestContext) -> ResponseEnvelope[AttendanceQrResponse]:
        data = await self._checkin.update_location(body, scope, ctx)
        message = "Gym location saved" if body.latitude is not None else "Gym location cleared"
        return ResponseEnvelope.ok(AttendanceQrResponse(**data), message=message)

    async def devices(self, scope: BranchScope) -> ResponseEnvelope[list[LinkedDeviceResponse]]:
        return ResponseEnvelope.ok([LinkedDeviceResponse(**d) for d in await self._checkin.devices(scope)])

    async def unlink_device(self, device_id: UUID, scope: BranchScope,
                            ctx: RequestContext) -> ResponseEnvelope[None]:
        await self._checkin.unlink(device_id, scope, ctx)
        return ResponseEnvelope.ok(None, message="Phone unlinked")

    # ── public scan page ─────────────────────────────────────────────────
    async def checkin_info(self, token: str, request: Request) -> ResponseEnvelope[CheckinInfoResponse]:
        data = await self._checkin.info(token, request.cookies.get(DEVICE_COOKIE_NAME))
        return ResponseEnvelope.ok(CheckinInfoResponse(**data))

    async def checkin_verify(self, token: str, body: CheckinVerify, request: Request,
                             response: Response) -> ResponseEnvelope[CheckinPerson]:
        ip = request.client.host if request.client else "unknown"
        person, device_token = await self._checkin.verify(token, body, request.cookies.get(DEVICE_COOKIE_NAME), ip,
                                                          request.headers.get("user-agent"))
        response.set_cookie(DEVICE_COOKIE_NAME, device_token, max_age=DEVICE_COOKIE_MAX_AGE, httponly=True,
                            secure=settings.COOKIE_SECURE, samesite="lax", path=DEVICE_COOKIE_PATH)
        return ResponseEnvelope.ok(CheckinPerson(**person), message=f"Phone linked to {person['name']}")

    async def checkin_scan(self, token: str, body: CheckinScan, request: Request) -> ResponseEnvelope[CheckResult]:
        data = await self._checkin.scan(token, body, request.cookies.get(DEVICE_COOKIE_NAME))
        return ResponseEnvelope.ok(CheckResult(**data), message=_result_message(data))
