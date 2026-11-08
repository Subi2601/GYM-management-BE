"""Organizations business logic — platform superadmin onboarding of a gym (org + first branch + OWNER)."""
from __future__ import annotations

from iam_core import RequestContext
from shared.exceptions.http_exceptions import ConflictError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Branch, Organization
from app.repositories.organization_repository import OrganizationRepository
from app.services.branch_service import BranchService
from app.services.plan_category_service import PlanCategoryService


class OrganizationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = OrganizationRepository(db)
        self._branches = BranchService(db)

    @staticmethod
    def org_out(o: Organization, branch_count: int) -> dict:
        return {"id": o.id, "name": o.name, "code": o.code, "contact_email": o.contact_email,
                "contact_phone": o.contact_phone, "is_active": o.is_active, "branch_count": branch_count,
                "created_at": o.created_at, "updated_at": o.updated_at}

    async def list_organizations(self, *, offset: int, limit: int, search: str | None) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_organizations_with_counts(offset=offset, limit=limit, search=search)
        return [self.org_out(o, n) for o, n in rows], total

    async def onboard(self, data, ctx: RequestContext) -> dict:
        code = data.code.upper()
        if await self._repo.code_taken(code):
            raise ConflictError("An organization with this code already exists")
        await self._branches.ensure_login_email_free(data.owner_email)
        org = await self._repo.add(Organization(name=data.name, code=code, contact_email=data.contact_email,
                                                contact_phone=data.contact_phone, created_by=ctx.user_id))
        branch = await self._repo.add(Branch(organization_id=org.id, branch_name=data.branch_name,
                                             location=data.branch_location, created_by=ctx.user_id))
        owner = await self._branches.create_owner_login(
            organization_id=org.id, branch_id=branch.id, name=data.owner_name, email=data.owner_email,
            password=data.owner_password, actor_id=ctx.user_id)
        await PlanCategoryService(self._db).create_defaults(org.id, ctx.user_id)
        ids = (org.id, branch.id, owner.id, owner.email)   # read before commit expires them
        await self._repo.commit()
        org_id, branch_id, owner_id, owner_email = ids
        org = await self._repo.get_organization(org_id)
        branch = await self._repo.get_branch(org_id, branch_id)
        return {**self.org_out(org, 1), "branch_id": branch.id, "branch_name": branch.branch_name,
                "owner_user_id": owner_id, "owner_email": owner_email}
