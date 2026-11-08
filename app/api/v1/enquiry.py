"""Enquiry form routes.

Public (no login, AuthMiddleware skips /api/v1/public/): the branch comes from the link token.
Staff: the branch's link (create on first visit) and regenerate. Registered before the leads router so
/leads/enquiry-form isn't read as a lead id.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Request
from iam_core import require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.enquiry_controller import EnquiryController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope
from app.schemas.enquiry import EnquiryFormInfo, EnquiryLink, EnquiryResult, EnquirySubmit

public_router = APIRouter(prefix="/api/v1/public/enquiry", tags=["public enquiry form"])

_TOKEN = Path(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@public_router.get("/{token}", response_model=ResponseEnvelope[EnquiryFormInfo])
async def enquiry_form_info(token: str = _TOKEN, controller: EnquiryController = Depends()):
    return await controller.form_info(token)


@public_router.post("/{token}", response_model=ResponseEnvelope[EnquiryResult], status_code=201)
async def submit_enquiry(body: EnquirySubmit, request: Request, token: str = _TOKEN,
                         controller: EnquiryController = Depends()):
    """Leave details → a NEW lead in the branch (or a note + follow-up on their open lead)."""
    return await controller.submit(token, body, request)


router = APIRouter(prefix="/api/v1/leads/enquiry-form", tags=["leads"])


@router.get("", response_model=ResponseEnvelope[EnquiryLink],
            dependencies=[Depends(require_permission("lead:list"))])
async def enquiry_link(scope: BranchScope = Depends(get_branch_scope), controller: EnquiryController = Depends()):
    """The selected branch's public form link token (made on first visit)."""
    return await controller.link(scope)


@router.post("/regenerate", response_model=ResponseEnvelope[EnquiryLink],
             dependencies=[Depends(require_permission("lead:create"))])
async def regenerate_enquiry_link(scope: BranchScope = Depends(get_branch_scope),
                                  controller: EnquiryController = Depends()):
    return await controller.regenerate(scope)
