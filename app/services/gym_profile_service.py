"""Gym profile — the gym's identity set on the Gym Settings page: name, logo, tagline, contacts, GSTIN, address,
invoice footer and the terms & conditions PDF. Used on invoices (letterhead), the welcome WhatsApp message (terms
link), the enquiry form and the sidebar. Logo and terms are served publicly by gym code so links work for members.
"""
from __future__ import annotations

import base64
import binascii
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization, OrgFile
from app.repositories.gym_profile_repository import GymProfileRepository

LOGO, TERMS = "LOGO", "TERMS"
LIMITS = {LOGO: (1 * 1024 * 1024, ("image/png", "image/jpeg", "image/webp"), "a PNG, JPG or WEBP image up to 1 MB"),
          TERMS: (5 * 1024 * 1024, ("application/pdf",), "a PDF up to 5 MB")}
_FIELDS = {"name": "name", "tagline": "tagline", "email": "contact_email", "phone": "contact_phone",
           "address": "address", "gstin": "gstin", "invoice_footer": "invoice_footer"}


def file_url(code: str, f: OrgFile | None) -> str | None:
    """Public link (versioned so a new upload isn't served from cache)."""
    if f is None:
        return None
    path = "logo" if f.kind == LOGO else "terms"
    return f"/api/v1/public/gyms/{code}/{path}?v={int(f.updated_at.timestamp())}"


class GymProfileService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = GymProfileRepository(db)

    async def _org(self, organization_id: UUID) -> Organization:
        org = await self._repo.get_org(organization_id)
        if org is None:
            raise NotFoundError("Gym")
        return org

    async def links(self, org: Organization) -> dict:
        files = await self._repo.files(org.id)
        terms = files.get(TERMS)
        return {"logo_url": file_url(org.code, files.get(LOGO)), "terms_url": file_url(org.code, terms),
                "terms_file_name": terms.file_name if terms else None}

    async def profile(self, organization_id: UUID) -> dict:
        org = await self._org(organization_id)
        return {"code": org.code, "name": org.name, "tagline": org.tagline, "email": org.contact_email,
                "phone": org.contact_phone, "address": org.address, "gstin": org.gstin,
                "invoice_footer": org.invoice_footer, **await self.links(org)}

    async def update(self, organization_id: UUID, data, actor: RequestContext) -> dict:
        org = await self._org(organization_id)
        for field, column in _FIELDS.items():
            if field in data.model_fields_set:
                value = getattr(data, field)
                value = value.strip() if isinstance(value, str) else value
                if field == "name" and not value:
                    continue                                   # the gym always keeps a name
                setattr(org, column, value or None)
        org.updated_by = actor.user_id
        await self._repo.commit()
        return await self.profile(organization_id)

    async def upload(self, organization_id: UUID, kind: str, data, actor: RequestContext) -> dict:
        max_bytes, types, what = LIMITS[kind]
        if data.content_type not in types:
            raise BadRequestError(f"Upload {what}")
        try:
            raw = base64.b64decode(data.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BadRequestError("The file couldn't be read. Upload it again") from exc
        if len(raw) > max_bytes:
            raise BadRequestError(f"Too big. Upload {what}")
        org = await self._org(organization_id)
        f = await self._repo.file(org.id, kind, with_data=True)
        if f is None:
            f = await self._repo.add(OrgFile(organization_id=org.id, kind=kind, file_name=data.file_name.strip(),
                                             content_type=data.content_type, size_bytes=len(raw), data=raw,
                                             created_by=actor.user_id))
        else:
            f.file_name, f.content_type, f.size_bytes, f.data = (data.file_name.strip(), data.content_type,
                                                                 len(raw), raw)
            f.updated_by = actor.user_id
        await self._repo.commit()
        return await self.profile(organization_id)

    async def remove(self, organization_id: UUID, kind: str) -> dict:
        org = await self._org(organization_id)
        f = await self._repo.file(org.id, kind)
        if f is not None:
            await self._repo.hard_delete(f)
            await self._repo.commit()
        return await self.profile(organization_id)

    async def public_file(self, code: str, kind: str) -> OrgFile:
        org = await self._repo.org_by_code(code)
        f = await self._repo.file(org.id, kind, with_data=True) if org else None
        if f is None:
            raise NotFoundError("File")
        return f
