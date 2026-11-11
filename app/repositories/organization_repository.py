"""DB operations for organizations and branches. No business logic."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from app.models.organization import Branch, Organization
from app.models.user import User
from app.core.enums import AccountRole
from app.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository):

    # ── organizations ────────────────────────────────────────────────────
    async def get_organization(self, org_id: UUID) -> Organization | None:
        stmt = self.alive(Organization, select(Organization).where(Organization.id == org_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_organization_by_code(self, code: str) -> Organization | None:
        stmt = self.alive(Organization, select(Organization).where(func.lower(Organization.code) == code.lower()))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_organizations(self, *, offset: int, limit: int,
                                 search: str | None = None) -> tuple[list[Organization], int]:
        stmt = self.alive(Organization, select(Organization))
        if search:
            stmt = stmt.where(Organization.name.ilike(f"%{search}%"))
        return await self.paginate_scalars(stmt.order_by(Organization.name), offset=offset, limit=limit)

    # ── branches ─────────────────────────────────────────────────────────
    async def get_branch(self, org_id: UUID, branch_id: UUID) -> Branch | None:
        stmt = self.alive(Branch, select(Branch).where(Branch.id == branch_id,
                                                       Branch.organization_id == org_id))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def get_branch_by_name(self, org_id: UUID, name: str) -> Branch | None:
        stmt = self.alive(Branch, select(Branch).where(Branch.organization_id == org_id,
                                                       func.lower(Branch.branch_name) == name.lower()))
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def list_branches(self, org_id: UUID) -> list[Branch]:
        stmt = self.alive(Branch, select(Branch).where(Branch.organization_id == org_id))
        return list((await self._db.execute(stmt.order_by(Branch.created_at))).scalars().all())

    async def list_branch_ids(self, org_id: UUID) -> list[UUID]:
        stmt = self.alive(Branch, select(Branch.id).where(Branch.organization_id == org_id))
        return list((await self._db.execute(stmt)).scalars().all())

    async def branch_owner_login(self, branch_id: UUID) -> User | None:
        """The OWNER login created together with the branch (oldest one wins)."""
        stmt = self.alive(User, select(User).where(User.branch_id == branch_id, User.role == AccountRole.OWNER))
        return (await self._db.execute(stmt.order_by(User.created_at).limit(1))).scalar_one_or_none()

    # ── uniqueness checks (soft-deleted rows still hold the DB unique keys) ─
    async def code_taken(self, code: str) -> bool:
        stmt = select(Organization.id).where(func.lower(Organization.code) == code.lower()).limit(1)
        return (await self._db.execute(stmt)).first() is not None

    async def branch_name_taken(self, org_id: UUID, name: str, exclude_id: UUID | None = None) -> bool:
        stmt = select(Branch.id).where(Branch.organization_id == org_id, Branch.is_delete.is_(False),
                                       func.lower(Branch.branch_name) == name.lower())
    
        if exclude_id is not None:
            stmt = stmt.where(Branch.id != exclude_id, )
        return (await self._db.execute(stmt.limit(1))).first() is not None

    # ── listings ─────────────────────────────────────────────────────────
    async def list_organizations_with_counts(self, *, offset: int, limit: int,
                                             search: str | None = None) -> tuple[list, int]:
        """Rows: (Organization, branch_count)."""
        counts = (select(Branch.organization_id, func.count(Branch.id).label("n"))
                  .where(Branch.is_delete.is_(False)).group_by(Branch.organization_id).subquery())
        stmt = self.alive(Organization, select(Organization, func.coalesce(counts.c.n, 0))
                          .outerjoin(counts, counts.c.organization_id == Organization.id))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(Organization.name.ilike(pattern) | Organization.code.ilike(pattern))
        return await self.paginate(stmt.order_by(Organization.name), offset=offset, limit=limit)

    async def count_branches(self, org_id: UUID) -> int:
        stmt = self.alive(Branch, select(func.count(Branch.id)).where(Branch.organization_id == org_id))
        return (await self._db.execute(stmt)).scalar_one()

    async def page_branches(self, org_id: UUID, *, offset: int, limit: int,
                            search: str | None = None) -> tuple[list[Branch], int]:
        stmt = self.alive(Branch, select(Branch).where(Branch.organization_id == org_id))
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(Branch.branch_name.ilike(pattern) | Branch.location.ilike(pattern))
        return await self.paginate_scalars(stmt.order_by(Branch.created_at), offset=offset, limit=limit)

    async def branch_counts(self, branch_ids: list[UUID]) -> dict[UUID, tuple[int, int]]:
        """branch_id → (members, active staff)."""
        if not branch_ids:
            return {}
        from app.core.enums import EmployeeStatus
        from app.models.member import Member
        from app.models.staff import Employee
        members = dict((await self._db.execute(
            select(Member.branch_id, func.count(Member.id)).where(Member.branch_id.in_(branch_ids),
                                                                  Member.is_delete.is_(False))
            .group_by(Member.branch_id))).all())
        staff = dict((await self._db.execute(
            select(Employee.branch_id, func.count(Employee.id)).where(Employee.branch_id.in_(branch_ids),
                                                                      Employee.is_delete.is_(False),
                                                                      Employee.status == EmployeeStatus.ACTIVE)
            .group_by(Employee.branch_id))).all())
        return {b: (members.get(b, 0), staff.get(b, 0)) for b in branch_ids}

    async def clear_head_office(self, org_id: UUID, keep_id: UUID) -> None:
        for b in await self.list_branches(org_id):
            if b.id != keep_id and b.is_head_office:
                b.is_head_office = False

    async def branch_owner_emails(self, branch_ids: list[UUID]) -> dict[UUID, str]:
        """branch_id → email of its OWNER login (oldest per branch), same rule as branch_owner_login."""
        if not branch_ids:
            return {}
        stmt = self.alive(User, select(User.branch_id, User.email)
                          .where(User.branch_id.in_(branch_ids), User.role == AccountRole.OWNER)
                          .order_by(User.created_at))
        out: dict[UUID, str] = {}
        for branch_id, email in (await self._db.execute(stmt)).all():
            out.setdefault(branch_id, email)
        return out
