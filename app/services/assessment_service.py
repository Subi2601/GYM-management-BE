"""Client assessments — taken at joining and again later to track progress. The newest one keeps the member's
height / weight on the profile in step."""
from __future__ import annotations

from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.scope import BranchScope
from app.models.membership import MemberAssessment
from app.repositories.assessment_repository import AssessmentRepository

_FIELDS = ("assessed_on", "height_cm", "weight_kg", "body_fat_percent", "waist_cm", "resting_heart_rate",
           "bp_systolic", "bp_diastolic", "lifestyle", "medical_conditions", "past_injuries", "surgeries",
           "static_notes", "dynamic_notes", "notes")
_TEXT = ("medical_conditions", "past_injuries", "surgeries", "static_notes", "dynamic_notes", "notes")


def bmi(height_cm: float | None, weight_kg: float | None) -> float | None:
    if not height_cm or not weight_kg:
        return None
    return round(weight_kg / (height_cm / 100) ** 2, 1)


class AssessmentService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = AssessmentRepository(db)

    @staticmethod
    def assessment_out(a: MemberAssessment, assessed_by: str | None) -> dict:
        out = {f: getattr(a, f) for f in _FIELDS}
        return {**out, "id": a.id, "member_id": a.member_id, "bmi": bmi(a.height_cm, a.weight_kg),
                "movements": dict(a.movements or {}), "assessed_by_name": assessed_by,
                "created_at": a.created_at, "updated_at": a.updated_at}

    async def _member(self, member_id: UUID, scope: BranchScope):
        member = await self._repo.get_member(member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        return member

    async def list_for_member(self, member_id: UUID, scope: BranchScope) -> list[dict]:
        await self._member(member_id, scope)
        return [self.assessment_out(*r) for r in await self._repo.list_for_member(member_id, scope)]

    async def _get(self, assessment_id: UUID, scope: BranchScope) -> dict:
        row = await self._repo.get_row(assessment_id, scope)
        if row is None:
            raise NotFoundError("Assessment")
        return self.assessment_out(*row)

    @staticmethod
    def _apply(a: MemberAssessment, data) -> None:
        if data.assessed_on > timeutil.today():
            raise BadRequestError("The assessment date can't be in the future")
        for f in _FIELDS:
            value = getattr(data, f)
            if f in _TEXT:
                value = (value or "").strip() or None
            setattr(a, f, value)
        a.movements = {k: v for k, v in data.movements.items()}

    async def _sync_profile(self, member, a: MemberAssessment) -> None:
        if await self._repo.latest_on_or_after(member.id, a):
            member.height = a.height_cm or member.height
            member.weight = a.weight_kg or member.weight

    async def create(self, member_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        member = await self._member(member_id, scope)
        a = MemberAssessment(organization_id=member.organization_id, branch_id=member.branch_id,
                             member_id=member.id, created_by=actor.user_id)
        self._apply(a, data)
        await self._repo.add(a)
        await self._sync_profile(member, a)
        await self._repo.commit()
        return await self._get(a.id, scope)

    async def update(self, assessment_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        a = await self._repo.get(assessment_id, scope)
        if a is None:
            raise NotFoundError("Assessment")
        self._apply(a, data)
        a.updated_by = actor.user_id
        await self._sync_profile(await self._member(a.member_id, scope), a)
        await self._repo.commit()
        return await self._get(a.id, scope)

    async def delete(self, assessment_id: UUID, scope: BranchScope, actor: RequestContext) -> None:
        scope.require_branch()
        a = await self._repo.get(assessment_id, scope)
        if a is None:
            raise NotFoundError("Assessment")
        a.soft_delete(actor.user_id)
        await self._repo.commit()
