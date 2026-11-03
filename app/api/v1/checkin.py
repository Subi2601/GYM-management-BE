"""Public QR check-in routes (no login) — opened from the branch's CHECK IN / CHECK OUT posters.

The branch comes from the poster token; the person from the phone's linked-device cookie.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request, Response
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.attendance_controller import AttendanceController
from app.schemas.attendance import CheckinInfoResponse, CheckinPerson, CheckinScan, CheckinVerify, CheckResult

router = APIRouter(prefix="/api/v1/public/checkin", tags=["public check-in"])

_TOKEN = Path(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/{token}", response_model=ResponseEnvelope[CheckinInfoResponse])
async def checkin_info(request: Request, token: str = _TOKEN, controller: AttendanceController = Depends()):
    return await controller.checkin_info(token, request)


@router.post("/{token}/verify", response_model=ResponseEnvelope[CheckinPerson])
async def checkin_verify(body: CheckinVerify, request: Request, response: Response, token: str = _TOKEN,
                         controller: AttendanceController = Depends()):
    return await controller.checkin_verify(token, body, request, response)


@router.post("/{token}/scan", response_model=ResponseEnvelope[CheckResult])
async def checkin_scan(body: CheckinScan, request: Request, token: str = _TOKEN,
                       controller: AttendanceController = Depends()):
    return await controller.checkin_scan(token, body, request)
