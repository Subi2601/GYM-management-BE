"""DB operations for client assessments. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.scope import BranchScope
from app.models.member import Member
from app.models.membership import MemberAssessment
from app.models.user import User
from app.repositories.base import BaseRepository


class AssessmentRepository(BaseRepository):

    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    def _rows(self, scope: BranchScope):
        stmt = select(MemberAssessment, User.name).outerjoin(User, User.id == MemberAssessment.created_by)
        return self.scoped(MemberAssessment, stmt, scope)

    async def list_for_member(self, member_id: UUID, scope: BranchScope) -> list:
        """(assessment, assessed-by name), newest first."""
        stmt = (self._rows(scope).where(MemberAssessment.member_id == member_id)
                .order_by(MemberAssessment.assessed_on.desc(), MemberAssessment.created_at.desc()))
        return list((await self._db.execute(stmt)).all())

    async def get_row(self, assessment_id: UUID, scope: BranchScope):
        return (await self._db.execute(self._rows(scope).where(MemberAssessment.id == assessment_id))).first()

    async def get(self, assessment_id: UUID, scope: BranchScope) -> MemberAssessment | None:
        return await self.get_scoped(MemberAssessment, assessment_id, scope)

    async def latest_on_or_after(self, member_id: UUID, assessment: MemberAssessment) -> bool:
        """True when no other assessment of the member is newer than this one."""
        stmt = (self.alive(MemberAssessment, select(MemberAssessment.id))
                .where(MemberAssessment.member_id == member_id, MemberAssessment.id != assessment.id,
                       MemberAssessment.assessed_on > assessment.assessed_on).limit(1))
        return (await self._db.execute(stmt)).first() is None
