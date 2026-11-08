"""Members business logic — registration ids, uniqueness, PII, derived membership state."""
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.encryption import decrypt_pii, encrypt_pii, mask_pii
from app.core.enums import Gender, MembershipState
from app.core.scope import BranchScope
from app.models.member import Member
from app.repositories.member_repository import MemberRepository
from app.services.settings_service import DEFAULTS, SettingsService

_PLAIN_FIELDS = ("name", "phone", "email", "gender", "dob", "address", "blood_group", "weight", "height",
                 "fitness_goal", "emergency_contact_name", "emergency_contact_phone", "joining_date",
                 "id_proof_type", "status")


def membership_state(end_date: date | None, today: date,
                     due_days: int = DEFAULTS.renewal_due_days) -> MembershipState:
    if end_date is None:
        return MembershipState.NO_PLAN
    if end_date < today:
        return MembershipState.EXPIRED
    if end_date <= today + timedelta(days=due_days):
        return MembershipState.EXPIRING
    return MembershipState.ACTIVE


class MemberService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = MemberRepository(db)
        self._settings = SettingsService(db)

    async def _due_days(self, scope: BranchScope) -> int:
        return (await self._settings.values(scope.organization_id)).renewal_due_days

    # ── output builder ───────────────────────────────────────────────────
    @staticmethod
    def member_out(m: Member, plan_id: UUID | None, plan_name: str | None, end_date: date | None,
                   last_visit: date | None = None, referred_by_name: str | None = None, referral_count: int = 0,
                   *, show_pii: bool, today: date, due_days: int = DEFAULTS.renewal_due_days) -> dict:
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
            "membership_state": membership_state(end_date, today, due_days),
            "current_plan_id": plan_id, "current_plan_name": plan_name, "expiry_date": end_date,
            "last_visit_date": last_visit,
            "referred_by_id": m.referred_by_id, "referred_by_name": referred_by_name, "referral_count": referral_count,
            "days_since_visit": (today - last_visit).days if last_visit else None,
            "created_at": m.created_at, "updated_at": m.updated_at,
        }

    # ── queries ──────────────────────────────────────────────────────────
    async def list_members(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                           state_filter: str | None, plan_id: UUID | None, gender: Gender | None,
                           joined_from: date | None, joined_to: date | None, sort_by: str | None,
                           sort_dir: str, show_pii: bool) -> tuple[list[dict], int]:
        if joined_from and joined_to and joined_from > joined_to:
            raise BadRequestError("joined_from must be on or before joined_to")
        today, s = timeutil.today(), await self._settings.values(scope.organization_id)
        due_days = s.renewal_due_days
        rows, total = await self._repo.list_members(scope, offset=offset, limit=limit, today=today,
                                                    due_days=due_days, absent_days=s.absent_alert_days,
                                                    search=search, state_filter=state_filter, plan_id=plan_id,
                                                    gender=gender, joined_from=joined_from, joined_to=joined_to,
                                                    sort_by=sort_by, sort_dir=sort_dir)
        return [self.member_out(*r, show_pii=show_pii, today=today, due_days=due_days) for r in rows], total

    async def get_member(self, member_id: UUID, scope: BranchScope, show_pii: bool) -> dict:
        row = await self._repo.get_member_row(member_id, scope)
        if row is None:
            raise NotFoundError("Member")
        return self.member_out(*row, show_pii=show_pii, today=timeutil.today(), due_days=await self._due_days(scope))

    async def next_registration_id(self, scope: BranchScope) -> str:
        """<prefix>-001: the gym's member id prefix (Gym settings), the gym code by default."""
        prefix = (await self._settings.values(scope.organization_id)).member_id_prefix
        return f"{prefix}-{await self._repo.last_registration_number(scope.organization_id, prefix) + 1:03d}"

    async def counts(self, scope: BranchScope) -> dict:
        s = await self._settings.values(scope.organization_id)
        return await self._repo.tab_counts(scope, timeutil.today(), s.renewal_due_days, s.absent_alert_days)

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
        referrer = getattr(data, "referred_by_id", None)
        if referrer:
            await self._check_referrer(referrer, None, scope)
            member.referred_by_id = referrer
        return await self._repo.add(member)

    async def _check_referrer(self, referrer_id: UUID, member_id: UUID | None, scope: BranchScope) -> None:
        """The referrer is a member of this gym (any branch), not the member themself, and no loop
        (A referred B referred A)."""
        if referrer_id == member_id:
            raise BadRequestError("A member can't refer themself")
        chain = await self._repo.referrer_chain(referrer_id, scope.organization_id)
        if not chain:
            raise NotFoundError("Referring member")
        if member_id is not None and member_id in chain:
            raise BadRequestError("That would make a loop: this member is already above them in the referral tree")

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
        if "referred_by_id" in sent and data.referred_by_id != member.referred_by_id:
            if data.referred_by_id is not None:
                await self._check_referrer(data.referred_by_id, member.id, scope)
            member.referred_by_id = data.referred_by_id
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
