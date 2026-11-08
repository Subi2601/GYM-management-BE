"""Public routes (no login): QR check-in from the branch posters, and invoices shared on WhatsApp.

Check-in: the branch comes from the poster token, the person from the phone's linked-device cookie.
Invoice: the signed share token is the permission.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request, Response
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.attendance_controller import AttendanceController
from app.controllers.payment_controller import PaymentController
from app.schemas.attendance import CheckinInfoResponse, CheckinPerson, CheckinScan, CheckinVerify, CheckResult
from app.schemas.payment import InvoiceResponse

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


invoice_router = APIRouter(prefix="/api/v1/public/invoice", tags=["public invoice"])


@invoice_router.get("/{token}", response_model=ResponseEnvelope[InvoiceResponse])
async def public_invoice(token: str = Path(min_length=56, max_length=56, pattern=r"^[0-9a-f]+$"),
                         controller: PaymentController = Depends()):
    return await controller.public_invoice(token)
