"""Members business logic — registration ids, uniqueness, PII, derived membership state."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.encryption import decrypt_pii, encrypt_pii, mask_pii
from app.core.enums import MembershipState
from app.core.scope import BranchScope
from app.models.member import Member
from app.repositories.member_repository import EXPIRING_WINDOW_DAYS, MemberRepository

_PLAIN_FIELDS = ("name", "phone", "email", "gender", "dob", "address", "blood_group", "weight", "height",
                 "fitness_goal", "emergency_contact_name", "emergency_contact_phone", "joining_date",
                 "id_proof_type", "status")


def membership_state(end_date: date | None, today: date) -> MembershipState:
    if end_date is None:
        return MembershipState.NO_PLAN
    if end_date < today:
        return MembershipState.EXPIRED
    if end_date <= today + timedelta(days=EXPIRING_WINDOW_DAYS):
        return MembershipState.EXPIRING
    return MembershipState.ACTIVE


class MemberService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = MemberRepository(db)

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def member_out(m: Member, plan_id: UUID | None, plan_name: str | None, end_date: date | None,
                   *, show_pii: bool, today: date) -> dict:
        proof = decrypt_pii(m.id_proof_number_enc)
        return {
            "id": m.id, "branch_id": m.branch_id, "registration_id": m.registration_id,
            "name": m.name, "phone": m.phone, "email": m.email, "gender": m.gender, "dob": m.dob,
            "address": m.address, "blood_group": m.blood_group, "weight": m.weight, "height": m.height,
            "fitness_goal": m.fitness_goal, "emergency_contact_name": m.emergency_contact_name,
            "emergency_contact_phone": m.emergency_contact_phone, "joining_date": m.joining_date,
            "id_proof_type": m.id_proof_type,
            "id_proof_number": proof if show_pii else mask_pii(proof),
            "status": m.status,
            "membership_state": membership_state(end_date, today),
            "current_plan_id": plan_id, "current_plan_name": plan_name, "expiry_date": end_date,
            "created_at": m.created_at, "updated_at": m.updated_at,
        }

    # ── queries ──────────────────────────────────────────────────────────
    async def list_members(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                           state_filter: str | None, plan_id: UUID | None,
                           show_pii: bool) -> tuple[list[dict], int]:
        today = timeutil.today()
        rows, total = await self._repo.list_members(scope, offset=offset, limit=limit, today=today,
                                                    search=search, state_filter=state_filter, plan_id=plan_id)
        return [self.member_out(*r, show_pii=show_pii, today=today) for r in rows], total

    async def get_member(self, member_id: UUID, scope: BranchScope, show_pii: bool) -> dict:
        row = await self._repo.get_member_row(member_id, scope)
        if row is None:
            raise NotFoundError("Member")
        return self.member_out(*row, show_pii=show_pii, today=timeutil.today())

    async def next_registration_id(self, scope: BranchScope) -> str:
        return f"SG-{await self._repo.last_registration_number(scope.organization_id) + 1:03d}"

    async def counts(self, scope: BranchScope) -> dict:
        return {"total": await self._repo.count_members(scope),
                "active": await self._repo.count_with_active_membership(scope, timeutil.today())}

    # ── commands ─────────────────────────────────────────────────────────
    async def create_member(self, data, scope: BranchScope, actor: RequestContext, show_pii: bool) -> dict:
        branch_id = scope.require_branch()
        if await self._repo.get_by_phone(branch_id, data.phone):
            raise ConflictError("A member with this phone number already exists")
        member = await self._build_member(data, scope, branch_id, actor)
        await self._repo.commit()
        return await self.get_member(member.id, scope, show_pii)

    async def _build_member(self, data, scope: BranchScope, branch_id: UUID, actor: RequestContext) -> Member:
        """Shared by create_member and lead conversion — caller commits."""
        member = Member(
            organization_id=scope.organization_id, branch_id=branch_id,
            registration_id=await self.next_registration_id(scope),
            **{f: getattr(data, f) for f in _PLAIN_FIELDS if f != "joining_date"},
            joining_date=data.joining_date or timeutil.today(),
            id_proof_number_enc=encrypt_pii(data.id_proof_number),
            created_by=actor.user_id,
        )
        return await self._repo.add(member)

    async def update_member(self, member_id: UUID, data, scope: BranchScope, actor: RequestContext,
                            show_pii: bool) -> dict:
        member = await self._repo.get_member(member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        sent = data.model_fields_set
        if "phone" in sent and data.phone and data.phone != member.phone:
            existing = await self._repo.get_by_phone(member.branch_id, data.phone)
            if existing and existing.id != member.id:
                raise ConflictError("A member with this phone number already exists")
        for field in _PLAIN_FIELDS:
            if field in sent:
                value = getattr(data, field)
                if value is None and field in ("name", "phone", "gender", "joining_date", "status"):
                    continue  # required columns are never cleared
                setattr(member, field, value)
        if "id_proof_number" in sent:
            member.id_proof_number_enc = encrypt_pii(data.id_proof_number)
        member.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_member(member.id, scope, show_pii)

    async def delete_member(self, member_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        member = await self._repo.get_member(member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        if await self._repo.has_subscriptions(member_id):
            raise BadRequestError("Cannot delete member: subscriptions exist for this member")
        member.soft_delete(actor.user_id)
        await self._repo.commit()
