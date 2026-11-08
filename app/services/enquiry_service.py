"""Public enquiry form — a branch link / QR anyone can open (no login) to leave their details as a lead.

The link carries the branch's random `enquiry_token` (regenerate = old links / posters stop working). A submit
creates a NEW lead (source ENQUIRY_FORM, follow-up today, attended by nobody yet). If the same phone already has an
open lead in the branch, that lead gets a note and a follow-up today instead of a duplicate. Rate limited per
network address and per phone; a honeypot field drops simple bots.
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import LeadSource, LeadStatus
from app.core.ratelimit import SlidingWindowLimiter
from app.core.scope import BranchScope
from app.models.member import Lead
from app.models.organization import Branch
from app.repositories.enquiry_repository import EnquiryRepository
from app.services.lead_service import _append_note, _dmy, book_trial
from app.services.settings_service import SettingsService

# The public form books a trial from today up to this many days ahead.
TRIAL_BOOK_AHEAD_DAYS = 14

# Submits per network address per hour, and per phone per branch per day.
_PER_IP = SlidingWindowLimiter(limit=10, window_seconds=60 * 60)
_PER_PHONE = SlidingWindowLimiter(limit=3, window_seconds=24 * 60 * 60)

_TIME_LABEL = {"MORNING": "Morning", "AFTERNOON": "Afternoon", "EVENING": "Evening"}
_JOIN_LABEL = {"THIS_WEEK": "This week", "THIS_MONTH": "This month", "LATER": "Later"}
_JOIN_DAYS = {"THIS_WEEK": 3, "THIS_MONTH": 15}
# A lead in one of these states is closed: a new enquiry from that phone opens a fresh lead.
_CLOSED = (LeadStatus.JOINED,)


def _too_many() -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                         detail="Too many enquiries from here. Please try again later or call the gym")


class EnquiryService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = EnquiryRepository(db)
        self._settings = SettingsService(db)

    # ── public ───────────────────────────────────────────────────────────
    async def _branch(self, token: str):
        found = await self._repo.branch_by_token(token)
        if found is None:
            raise NotFoundError("Enquiry form")       # unknown or regenerated link
        return found

    async def form_info(self, token: str) -> dict:
        branch, org = await self._branch(token)
        s = await self._settings.values(org.id)
        from app.services.gym_profile_service import GymProfileService
        links = await GymProfileService(self._repo._db).links(org)
        return {"organization_name": org.name, "branch_name": branch.branch_name,
                "branch_location": branch.location, "contact_phone": branch.phone or org.contact_phone,
                "logo_url": links["logo_url"], "terms_url": links["terms_url"],
                "trial_enabled": s.trial_enabled, "trial_days": s.trial_days if s.trial_enabled else 0,
                "trial_fee": s.trial_fee if s.trial_enabled else 0,
                "trial_book_ahead_days": TRIAL_BOOK_AHEAD_DAYS if s.trial_enabled else 0}

    async def submit(self, token: str, data, ip: str) -> dict:
        branch, _ = await self._branch(token)
        today = timeutil.today()
        settings = await self._settings.values(branch.organization_id)
        if data.trial:                                # checked before the limits so a fix-and-resend still works
            if not settings.trial_enabled:
                raise BadRequestError("Trial classes aren't offered right now. Send the enquiry without a trial")
            if data.trial_date is None or not today <= data.trial_date <= today + timedelta(days=TRIAL_BOOK_AHEAD_DAYS):
                raise BadRequestError(f"Pick a trial start date within the next {TRIAL_BOOK_AHEAD_DAYS} days")
        if _PER_IP.blocked(ip):
            raise _too_many()
        _PER_IP.hit(ip)
        result = {"name": data.name.strip(), "branch_name": branch.branch_name}
        if data.website:                              # honeypot filled → pretend success, store nothing
            return result
        phone_key = f"{branch.id}:{data.phone}"
        if _PER_PHONE.blocked(phone_key):
            raise _too_many()
        _PER_PHONE.hit(phone_key)

        details = [f"Enquiry form: {data.name.strip()}"]
        if data.preferred_time:
            details.append(f"prefers {_TIME_LABEL[data.preferred_time].lower()}")
        if data.join_when:
            details.append(f"plans to join {_JOIN_LABEL[data.join_when].lower()}")
        if data.message and data.message.strip():
            details.append(f'says "{data.message.strip()}"')
        note = " · ".join(details)
        join_date = today + timedelta(days=_JOIN_DAYS[data.join_when]) if data.join_when in _JOIN_DAYS else None

        lead = await self._repo.latest_lead_by_phone(branch.id, data.phone)
        if lead is not None and lead.status not in _CLOSED:
            # Same person again: keep one lead, bring it back to today's follow-ups.
            lead.notes = _append_note(lead.notes, f"Enquired again. {note}")
            lead.next_follow_up_date = today
            if lead.status in (LeadStatus.NOT_INTERESTED, LeadStatus.JOINED_ELSEWHERE):
                lead.status = LeadStatus.FOLLOW_UP
            lead.goal = lead.goal or data.goal
            lead.location = lead.location or (data.location or "").strip() or None
            lead.plan_to_join_date = join_date or lead.plan_to_join_date
        else:
            lead = await self._repo.add(Lead(
                organization_id=branch.organization_id, branch_id=branch.id, name=data.name.strip(),
                phone=data.phone, location=(data.location or "").strip() or None, goal=data.goal,
                plan_to_join_date=join_date, source=LeadSource.ENQUIRY_FORM, status=LeadStatus.NEW,
                notes=_append_note(None, note), next_follow_up_date=today))

        if data.trial:
            if lead.trial_start is None:              # one trial per person (per open lead)
                lead.notes = _append_note(lead.notes, f"{book_trial(lead, data.trial_date, settings)}, "
                                                      f"booked on the enquiry form")
                result.update(trial_start=lead.trial_start, trial_end=lead.trial_end, trial_fee=lead.trial_fee)
            else:
                lead.notes = _append_note(lead.notes, f"Asked for a trial again (already had one from "
                                                      f"{_dmy(lead.trial_start)})")
                result["trial_used"] = True
        await self._repo.commit()
        return result

    # ── staff side ───────────────────────────────────────────────────────
    async def _scope_branch(self, scope: BranchScope) -> Branch:
        branch_id = scope.require_branch()
        branch = await self._repo.get_branch(branch_id, scope.organization_id)
        if branch is None:
            raise NotFoundError("Branch")
        return branch

    async def link(self, scope: BranchScope) -> dict:
        branch = await self._scope_branch(scope)
        if branch.enquiry_token is None:              # first visit creates the link
            await self._repo.set_token_if_missing(branch, secrets.token_urlsafe(24))
        return {"branch_id": branch.id, "branch_name": branch.branch_name, "token": branch.enquiry_token}

    async def regenerate(self, scope: BranchScope) -> dict:
        branch = await self._scope_branch(scope)
        branch.enquiry_token = secrets.token_urlsafe(24)
        await self._repo.commit()
        return {"branch_id": branch.id, "branch_name": branch.branch_name, "token": branch.enquiry_token}
