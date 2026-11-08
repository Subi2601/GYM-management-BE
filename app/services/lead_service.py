"""Leads business logic — follow-up history, conversion to member."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import LeadSource, LeadStatus, PaymentMode
from app.core.scope import BranchScope
from app.models.member import Lead
from app.repositories.lead_repository import LeadRepository
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberCreate
from app.services.member_service import MemberService
from app.services.settings_service import GymSettings, SettingsService

_FIELDS = ("name", "phone", "location", "goal", "source", "status", "plan_to_join_date", "next_follow_up_date",
           "notes", "referred_by_id")
_REQUIRED = ("name", "phone", "location", "goal", "source", "status", "plan_to_join_date")
NOTE_SEPARATOR = "\n---\n"
# How far back / ahead the desk may date a trial (a walk-in who started yesterday, a booking for next week).
TRIAL_BACKDATE_DAYS, TRIAL_AHEAD_DAYS = 7, 30
_MODE_LABEL = {PaymentMode.CASH: "Cash", PaymentMode.UPI: "UPI", PaymentMode.CARD: "Card",
               PaymentMode.BANK_TRANSFER: "Bank transfer"}


def _append_note(existing: str | None, text: str, author: str | None = None) -> str:
    """Dated history entry: "YYYY-MM-DD [Who]: text" (who = the account that recorded it)."""
    who = f" [{author}]" if author else ""
    line = f"{timeutil.today().isoformat()}{who}: {text}"
    return f"{existing}{NOTE_SEPARATOR}{line}" if existing else line


def _dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def trial_state(lead: Lead, today: date) -> str | None:
    if lead.trial_start is None or lead.trial_end is None:
        return None
    if today < lead.trial_start:
        return "UPCOMING"
    return "ON" if today <= lead.trial_end else "ENDED"


def book_trial(lead: Lead, start: date, settings: GymSettings) -> str:
    """Sets the trial dates and fee on a lead (caller checks the dates and commits). Returns the note text."""
    lead.trial_start = start
    lead.trial_end = start + timedelta(days=settings.trial_days - 1)
    lead.trial_fee = settings.trial_fee
    lead.trial_visits = 0
    lead.trial_last_visit = None
    fee = f", fee ₹{settings.trial_fee:,.0f} to pay at the gym" if settings.trial_fee else " (free)"
    return f"Trial booked: {settings.trial_days} day(s), {_dmy(lead.trial_start)} to {_dmy(lead.trial_end)}{fee}"


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = LeadRepository(db)
        self._members = MemberRepository(db)
        self._member_service = MemberService(db)
        self._settings = SettingsService(db)

    @staticmethod
    def lead_out(lead: Lead, attended_by_name: str | None = None, referred_by_name: str | None = None) -> dict:
        return {"id": lead.id, "branch_id": lead.branch_id, "name": lead.name, "phone": lead.phone,
                "location": lead.location, "goal": lead.goal, "source": lead.source, "status": lead.status,
                "plan_to_join_date": lead.plan_to_join_date, "next_follow_up_date": lead.next_follow_up_date,
                "last_follow_up_date": lead.last_follow_up_date, "notes": lead.notes,
                "converted_member_id": lead.converted_member_id,
                "attended_by_id": lead.created_by, "attended_by_name": attended_by_name,
                "referred_by_id": lead.referred_by_id, "referred_by_name": referred_by_name,
                "trial_start": lead.trial_start, "trial_end": lead.trial_end,
                "trial_state": trial_state(lead, timeutil.today()), "trial_fee": lead.trial_fee,
                "trial_paid_on": lead.trial_paid_on, "trial_payment_mode": lead.trial_payment_mode,
                "trial_visits": lead.trial_visits, "trial_last_visit": lead.trial_last_visit,
                "created_at": lead.created_at, "updated_at": lead.updated_at}

    # ── queries ──────────────────────────────────────────────────────────
    async def list_leads(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                         lead_filter: str | None, status: LeadStatus | None, source: LeadSource | None,
                         attended_by: UUID | None, follow_up_from: date | None, follow_up_to: date | None,
                         sort_by: str | None, sort_dir: str) -> tuple[list[dict], int]:
        if follow_up_from and follow_up_to and follow_up_from > follow_up_to:
            raise BadRequestError("follow_up_from must be on or before follow_up_to")
        rows, total = await self._repo.list_leads(scope, offset=offset, limit=limit, search=search,
                                                  lead_filter=lead_filter, status=status, source=source,
                                                  attended_by=attended_by, follow_up_from=follow_up_from,
                                                  follow_up_to=follow_up_to, sort_by=sort_by, sort_dir=sort_dir)
        return [self.lead_out(*r) for r in rows], total

    async def tab_counts(self, scope: BranchScope) -> dict:
        return await self._repo.tab_counts(scope)

    async def attendants(self, scope: BranchScope) -> list[dict]:
        return [{"id": uid, "name": name} for uid, name in await self._repo.attendants(scope)]

    async def get_lead(self, lead_id: UUID, scope: BranchScope) -> dict:
        row = await self._repo.get_lead_row(lead_id, scope)
        if row is None:
            raise NotFoundError("Lead")
        return self.lead_out(*row)

    async def _get(self, lead_id: UUID, scope: BranchScope) -> Lead:
        lead = await self._repo.get_lead(lead_id, scope)
        if lead is None:
            raise NotFoundError("Lead")
        return lead

    # ── commands ─────────────────────────────────────────────────────────
    async def _check_referrer(self, data, scope: BranchScope) -> None:
        if getattr(data, "referred_by_id", None) and not await self._members.referrer_chain(
                data.referred_by_id, scope.organization_id, limit=1):
            raise NotFoundError("Referring member")

    async def create_lead(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        await self._check_referrer(data, scope)
        lead = await self._repo.add(Lead(
            organization_id=scope.organization_id, branch_id=branch_id,
            **{f: getattr(data, f) for f in _FIELDS}, created_by=actor.user_id))
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    async def update_lead(self, lead_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        lead = await self._get(lead_id, scope)
        await self._check_referrer(data, scope)
        sent = data.model_fields_set
        for field in _FIELDS:
            if field in sent:
                value = getattr(data, field)
                if value is None and field in _REQUIRED:
                    continue  # required fields are never cleared
                setattr(lead, field, value)
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    async def delete_lead(self, lead_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        scope.require_branch()
        lead = await self._get(lead_id, scope)
        lead.soft_delete(actor.user_id)
        await self._repo.commit()

    async def add_follow_up(self, lead_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        lead = await self._get(lead_id, scope)
        if lead.converted_member_id is not None:
            raise BadRequestError("Lead has already been converted to a member")
        lead.notes = _append_note(lead.notes, data.notes, await self._repo.user_name(actor.user_id))
        lead.last_follow_up_date = timeutil.today()
        lead.next_follow_up_date = data.next_follow_up_date
        lead.status = data.status or LeadStatus.FOLLOW_UP
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    # ── trial class ──────────────────────────────────────────────────────
    async def _open_lead(self, lead_id: UUID, scope: BranchScope) -> Lead:
        scope.require_branch()
        lead = await self._get(lead_id, scope)
        if lead.status == LeadStatus.JOINED:
            raise BadRequestError(f"{lead.name} has already joined")
        return lead

    async def start_trial(self, lead_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        lead = await self._open_lead(lead_id, scope)
        settings = await self._settings.values(scope.organization_id)
        if not settings.trial_enabled:
            raise BadRequestError("Trial classes are switched off in Configuration")
        if lead.trial_start is not None:
            raise ConflictError(f"{lead.name} already had a trial ({_dmy(lead.trial_start)} to "
                                f"{_dmy(lead.trial_end)}). Cancel it first to book new dates")
        today = timeutil.today()
        if not today - timedelta(days=TRIAL_BACKDATE_DAYS) <= data.start_date <= today + timedelta(days=TRIAL_AHEAD_DAYS):
            raise BadRequestError(f"Trial start must be within {TRIAL_BACKDATE_DAYS} days before and "
                                  f"{TRIAL_AHEAD_DAYS} days after today")
        note = book_trial(lead, data.start_date, settings)
        lead.notes = _append_note(lead.notes, note, await self._repo.user_name(actor.user_id))
        lead.next_follow_up_date = lead.trial_end      # call when the trial ends: join or not
        if lead.status in (LeadStatus.NOT_INTERESTED, LeadStatus.JOINED_ELSEWHERE):
            lead.status = LeadStatus.FOLLOW_UP
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    async def cancel_trial(self, lead_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        lead = await self._open_lead(lead_id, scope)
        if lead.trial_start is None:
            raise BadRequestError(f"{lead.name} has no trial booked")
        if lead.trial_visits or lead.trial_paid_on:
            raise BadRequestError("This trial already has visits or a payment, so it can't be cancelled")
        lead.notes = _append_note(lead.notes, f"Trial cancelled ({_dmy(lead.trial_start)} to {_dmy(lead.trial_end)})",
                                  await self._repo.user_name(actor.user_id))
        lead.trial_start = lead.trial_end = lead.trial_fee = None
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    async def trial_visit(self, lead_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        lead = await self._open_lead(lead_id, scope)
        today = timeutil.today()
        state = trial_state(lead, today)
        if state is None:
            raise BadRequestError(f"{lead.name} has no trial booked")
        if state != "ON":
            raise BadRequestError(f"The trial runs {_dmy(lead.trial_start)} to {_dmy(lead.trial_end)}: "
                                  f"visits can be marked only on those days")
        if lead.trial_last_visit == today:
            raise ConflictError(f"{lead.name}'s trial visit is already marked today")
        if lead.trial_fee and lead.trial_paid_on is None:
            raise BadRequestError(f"Collect the trial fee ₹{lead.trial_fee:,.0f} first")
        lead.trial_visits += 1
        lead.trial_last_visit = today
        lead.notes = _append_note(lead.notes, f"Trial visit {lead.trial_visits}",
                                  await self._repo.user_name(actor.user_id))
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    async def trial_paid(self, lead_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        lead = await self._open_lead(lead_id, scope)
        if lead.trial_start is None:
            raise BadRequestError(f"{lead.name} has no trial booked")
        if not lead.trial_fee:
            raise BadRequestError("This trial is free")
        if lead.trial_paid_on is not None:
            raise ConflictError(f"Trial fee already paid on {_dmy(lead.trial_paid_on)}")
        lead.trial_paid_on = timeutil.today()
        lead.trial_payment_mode = data.payment_mode
        lead.notes = _append_note(lead.notes, f"Trial fee ₹{lead.trial_fee:,.0f} paid ({_MODE_LABEL[data.payment_mode]})",
                                  await self._repo.user_name(actor.user_id))
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    async def convert(self, lead_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        lead = await self._get(lead_id, scope)
        if lead.status == LeadStatus.JOINED:
            raise ConflictError("Lead has already joined")
        if await self._members.get_by_phone(branch_id, lead.phone):
            raise ConflictError(f"A member with phone {lead.phone} is already registered")
        member = await self._member_service._build_member(
            MemberCreate(name=lead.name, phone=lead.phone, fitness_goal=lead.goal, address=lead.location,
                         referred_by_id=lead.referred_by_id),
            scope, branch_id, actor)
        member_id, registration_id = member.id, member.registration_id   # read before commit expires them
        lead.status = LeadStatus.JOINED
        lead.notes = _append_note(lead.notes, f"Converted to Member. Registration ID: {registration_id}",
                                  await self._repo.user_name(actor.user_id))
        lead.next_follow_up_date = None
        lead.converted_member_id = member_id
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return {**await self.get_lead(lead_id, scope), "member_id": member_id, "registration_id": registration_id}
