"""Pydantic v2 schemas — gym profile (Gym Settings page)."""
from __future__ import annotations

import re

from pydantic import EmailStr, Field, field_validator
from shared.schemas.base_schema import TessBaseSchema

from app.schemas.common import FormSchema

GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z\d]Z[A-Z\d]$")


def check_gstin(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip().upper()
    if not GSTIN.match(v):
        raise ValueError("GSTIN has 15 characters, like 33ABCDE1234F1Z5")
    return v


class GymProfileUpdate(FormSchema):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    tagline: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=60)          # one or more numbers, as printed
    address: str | None = Field(default=None, max_length=300)
    gstin: str | None = None
    invoice_footer: str | None = Field(default=None, max_length=500)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        return check_gstin(v)


class GymFileUpload(FormSchema):
    file_name: str = Field(min_length=1, max_length=150)
    content_type: str = Field(max_length=80)
    data_base64: str = Field(min_length=4, max_length=7_000_000)


class GymProfile(TessBaseSchema):
    code: str                                 # Gym ID
    name: str
    tagline: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    gstin: str | None = None
    invoice_footer: str | None = None
    logo_url: str | None = None               # public, versioned
    terms_url: str | None = None              # public terms & conditions PDF
    terms_file_name: str | None = None
