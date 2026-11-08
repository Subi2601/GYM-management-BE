"""Enquiry form controller — public form + the staff-side link."""
from __future__ import annotations

from fastapi import Depends, Request
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.controllers.auth_controller import client_ip
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.enquiry import EnquiryFormInfo, EnquiryLink, EnquiryResult, EnquirySubmit
from app.services.enquiry_service import EnquiryService


class EnquiryController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = EnquiryService(db)

    async def form_info(self, token: str) -> ResponseEnvelope[EnquiryFormInfo]:
        return ResponseEnvelope.ok(EnquiryFormInfo(**await self._service.form_info(token)))

    async def submit(self, token: str, body: EnquirySubmit, request: Request) -> ResponseEnvelope[EnquiryResult]:
        data = await self._service.submit(token, body, client_ip(request) or "unknown")
        message = f"Thank you {data['name']}! {data['branch_name']} will call you soon"
        if data.get("trial_start"):
            message = (f"Thank you {data['name']}! Your trial at {data['branch_name']} starts "
                       f"{data['trial_start'].strftime('%d-%m-%Y')}")
        return ResponseEnvelope.ok(EnquiryResult(**data), message=message)

    async def link(self, scope: BranchScope) -> ResponseEnvelope[EnquiryLink]:
        return ResponseEnvelope.ok(EnquiryLink(**await self._service.link(scope)))

    async def regenerate(self, scope: BranchScope) -> ResponseEnvelope[EnquiryLink]:
        return ResponseEnvelope.ok(EnquiryLink(**await self._service.regenerate(scope)),
                                   message="New enquiry link made. Old links and posters no longer work")
