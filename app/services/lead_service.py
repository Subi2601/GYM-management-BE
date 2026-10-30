"""Leads business logic — follow-up history, conversion to member."""
from __future__ import annotations

from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import LeadStatus
from app.core.scope import BranchScope
from app.models.member import Lead
from app.repositories.lead_repository import LeadRepository
from app.repositories.member_repository import MemberRepository
from app.schemas.member import MemberCreate
from app.services.member_service import MemberService

_FIELDS = ("name", "phone", "location", "goal", "status", "plan_to_join_date", "next_follow_up_date", "notes")
_REQUIRED = ("name", "phone", "location", "goal", "status", "plan_to_join_date")
NOTE_SEPARATOR = "\n---\n"


def _append_note(existing: str | None, text: str) -> str:
    line = f"{timeutil.today().isoformat()}: {text}"
    return f"{existing}{NOTE_SEPARATOR}{line}" if existing else line


class LeadService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = LeadRepository(db)
        self._members = MemberRepository(db)
        self._member_service = MemberService(db)

    @staticmethod
    def lead_out(lead: Lead) -> dict:
        return {"id": lead.id, "branch_id": lead.branch_id, "name": lead.name, "phone": lead.phone,
                "location": lead.location, "goal": lead.goal, "status": lead.status,
                "plan_to_join_date": lead.plan_to_join_date, "next_follow_up_date": lead.next_follow_up_date,
                "last_follow_up_date": lead.last_follow_up_date, "notes": lead.notes,
                "converted_member_id": lead.converted_member_id,
                "created_at": lead.created_at, "updated_at": lead.updated_at}

    # ── queries ──────────────────────────────────────────────────────────
    async def list_leads(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                         lead_filter: str | None) -> tuple[list[dict], int]:
        leads, total = await self._repo.list_leads(scope, offset=offset, limit=limit, search=search,
                                                   lead_filter=lead_filter)
        return [self.lead_out(x) for x in leads], total

    async def get_lead(self, lead_id: UUID, scope: BranchScope) -> dict:
        return self.lead_out(await self._get(lead_id, scope))

    async def _get(self, lead_id: UUID, scope: BranchScope) -> Lead:
        lead = await self._repo.get_lead(lead_id, scope)
        if lead is None:
            raise NotFoundError("Lead")
        return lead

    # ── commands ─────────────────────────────────────────────────────────
    async def create_lead(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        lead = await self._repo.add(Lead(
            organization_id=scope.organization_id, branch_id=branch_id,
            **{f: getattr(data, f) for f in _FIELDS}, created_by=actor.user_id))
        await self._repo.commit()
        return await self.get_lead(lead.id, scope)

    async def update_lead(self, lead_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        lead = await self._get(lead_id, scope)
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
        lead.notes = _append_note(lead.notes, data.notes)
        lead.last_follow_up_date = timeutil.today()
        lead.next_follow_up_date = data.next_follow_up_date
        lead.status = data.status or LeadStatus.FOLLOW_UP
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
            MemberCreate(name=lead.name, phone=lead.phone, fitness_goal=lead.goal, address=lead.location),
            scope, branch_id, actor)
        member_id, registration_id = member.id, member.registration_id   # read before commit expires them
        lead.status = LeadStatus.JOINED
        lead.notes = _append_note(lead.notes, f"Converted to Member. Registration ID: {registration_id}")
        lead.next_follow_up_date = None
        lead.converted_member_id = member_id
        lead.updated_by = actor.user_id
        await self._repo.commit()
        return {**await self.get_lead(lead_id, scope), "member_id": member_id, "registration_id": registration_id}
