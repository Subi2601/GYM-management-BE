"""Pydantic v2 schemas — membership actions: freeze, transfer, cancel / refund, documents, refunds list."""
from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from shared.schemas.base_schema import TessBaseSchema

from app.core.enums import PaymentMode
from app.schemas.common import FormSchema, Phone

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
DOCUMENT_TYPES = ("application/pdf", "image/jpeg", "image/png", "image/webp")


class DocumentUpload(FormSchema):
    """A proof file sent with the action (base64, ≤ 5 MB; PDF or photo)."""
    file_name: str = Field(min_length=1, max_length=150)
    content_type: str
    data_base64: str = Field(min_length=4, max_length=7_000_000)

    @field_validator("content_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in DOCUMENT_TYPES:
            raise ValueError("Attach a PDF or a photo (JPG / PNG / WEBP)")
        return v


class ActionReason(FormSchema):
    reason: str = Field(min_length=3, max_length=1000)
    document: DocumentUpload | None = None


class FreezeRequest(ActionReason):
    start_date: date
    days: int = Field(ge=1, le=365)


class FreezeAllowance(FormSchema):
    """This member's own freeze days (None = back to the gym's days)."""
    days: int | None = Field(default=None, ge=0, le=365)


class TransferRequest(ActionReason):
    """To an existing member of the branch, or a new person (name + phone) registered on the spot."""
    to_member_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    phone: Phone | None = None

    @model_validator(mode="after")
    def _one_way(self) -> "TransferRequest":
        if self.to_member_id is None and not (self.name and self.phone):
            raise ValueError("pick an existing member or give a name and phone")
        return self


IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


class RefundDetails(FormSchema):
    amount: float = Field(gt=0)
    mode: PaymentMode
    reference: str | None = Field(default=None, max_length=80)          # UTR / transaction id
    account_holder: str | None = Field(default=None, max_length=120)
    account_number: str | None = Field(default=None, pattern=r"^\d{9,18}$")
    ifsc: str | None = None
    bank_name: str | None = Field(default=None, max_length=120)
    upi_id: str | None = Field(default=None, max_length=80, pattern=r"^[\w.\-]{2,}@[A-Za-z]{2,}$")

    @field_validator("ifsc")
    @classmethod
    def _ifsc(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip().upper()
        if not IFSC.match(v):
            raise ValueError("IFSC looks like SBIN0001234 (11 characters)")
        return v

    @model_validator(mode="after")
    def _bank(self) -> "RefundDetails":
        if self.mode == PaymentMode.BANK_TRANSFER and not (self.account_holder and self.account_number and self.ifsc):
            raise ValueError("Bank transfer needs the account holder, account number and IFSC")
        if self.mode == PaymentMode.UPI and not self.upi_id:
            raise ValueError("UPI refund needs the customer's UPI id")
        return self


class CancelRequest(ActionReason):
    refund: RefundDetails | None = None       # only when the membership is eligible for a refund


class FreezeOut(TessBaseSchema):
    id: UUID
    start_date: date
    end_date: date
    days: int
    resumed_on: date | None = None
    reason: str
    document_id: UUID | None = None
    document_name: str | None = None
    state: str                                # UPCOMING / ACTIVE / DONE


class FreezeStatus(TessBaseSchema):
    enabled: bool
    allowed: bool
    reason: str | None = None                 # why a new freeze isn't possible
    allowance_days: int
    custom_allowance: bool                    # this member's own days (not the gym's)
    gym_days: int
    used_days: int
    remaining_days: int
    times_used: int
    max_times: int
    active: FreezeOut | None = None           # running or upcoming freeze


class TransferStatus(TessBaseSchema):
    enabled: bool
    allowed: bool
    reason: str | None = None
    within_days: int
    used_days: int
    remaining_days: int                       # what the receiver gets


class CancelStatus(TessBaseSchema):
    refund_eligible: bool
    refund_reason: str | None = None          # why no refund
    refund_window_days: int
    used_days: int
    paid_amount: float                        # what was paid for this membership
    deduction_percent: float
    deduction_amount: float
    suggested_refund: float


class MembershipCurrent(TessBaseSchema):
    subscription_id: UUID
    plan_id: UUID
    plan_name: str
    start_date: date
    end_date: date
    frozen_days: int
    received_by_transfer: bool


class MembershipActions(TessBaseSchema):
    """GET /memberships/member/{id} — the membership the desk can act on and what is possible now."""
    current: MembershipCurrent | None = None
    reason: str | None = None                 # why nothing can be done (no running membership …)
    freezes: list[FreezeOut] = []
    freeze: FreezeStatus | None = None
    transfer: TransferStatus | None = None
    cancel: CancelStatus | None = None


class RefundOut(TessBaseSchema):
    id: UUID
    refund_no: str
    member_id: UUID
    member_name: str
    registration_id: str
    member_phone: str
    plan_name: str
    subscription_id: UUID
    paid_amount: float
    deduction_amount: float
    amount: float
    refund_date: date
    refund_mode: PaymentMode
    reason: str
    account_holder: str | None = None
    account_number: str | None = None         # masked unless pii:view
    ifsc: str | None = None
    bank_name: str | None = None
    upi_id: str | None = None
    reference: str | None = None


class DocumentOut(TessBaseSchema):
    id: UUID
    subscription_id: UUID | None = None
    kind: str                                 # FREEZE / TRANSFER / CANCEL
    file_name: str
    content_type: str
    size_bytes: int
    created_at: datetime


class ActionResult(TessBaseSchema):
    subscription_id: UUID
    member_id: UUID
    new_subscription_id: UUID | None = None   # transfer: the receiver's membership
    new_member_id: UUID | None = None
    refund: RefundOut | None = None
