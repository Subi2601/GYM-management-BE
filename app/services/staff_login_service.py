"""Staff app logins — the owner gives a staff member a login (email + a password the owner sets and shares by hand).

The login is homed in the employee's branch, so everything that user does is scoped to that branch automatically.
The owner knows the password, can sign in as the staff member to check their view, and can reset it any time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EmployeeRole, EmployeeStatus
from app.core.scope import BranchScope
from app.core.security import hash_password
from app.models.staff import Employee
from app.models.user import User
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.services.role_service import RoleService, account_kind


def default_role_code(role: EmployeeRole) -> str:
    """The gym role a new login gets unless one is picked: Manager for admin / manager staff, else Staff."""
    return "MANAGER" if role in (EmployeeRole.ADMIN, EmployeeRole.MANAGER, EmployeeRole.OWNER) else "STAFF"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StaffLoginService:
    def __init__(self, db: AsyncSession) -> None:
        self._employees = EmployeeRepository(db)
        self._users = UserRepository(db)
        self._orgs = OrganizationRepository(db)
        self._roles = RoleService(db)

    async def _employee(self, employee_id: UUID, scope: BranchScope) -> Employee:
        employee = await self._employees.get_employee(employee_id, scope)
        if employee is None:
            raise NotFoundError("Employee")
        return employee

    async def login_out(self, employee: Employee, user: User | None) -> dict:
        branch = await self._orgs.get_branch(employee.organization_id, employee.branch_id)
        role = await self._roles.login_role(user.id) if user else None
        if role is None:
            role = await self._roles.role_by_code(employee.organization_id, default_role_code(employee.role))
        return {"employee_id": employee.id, "has_login": user is not None,
                "enabled": bool(user and user.is_active), "email": user.email if user else employee.email,
                "role": user.role if user else account_kind(role.level),
                "role_id": role.id, "role_name": role.name, "role_level": role.level,
                "branch_id": employee.branch_id, "branch_name": branch.branch_name if branch else "",
                "last_login_at": user.last_login_at if user else None}

    async def get_login(self, employee_id: UUID, scope: BranchScope) -> dict:
        employee = await self._employee(employee_id, scope)
        return await self.login_out(employee, await self._users.get_employee_login(employee.id))

    async def save_login(self, employee_id: UUID, data, scope: BranchScope, actor: RequestContext) -> tuple[dict, str]:
        """Create the login (password required) or update it: role, optional new password, re-enable.
        Returns (login, message)."""
        scope.require_branch()
        employee = await self._employee(employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("A terminated employee cannot have a login")
        if not employee.email:
            raise BadRequestError("Add an email to the employee first — it is their login ID")
        email = employee.email.lower()
        user = await self._users.get_employee_login(employee.id)

        if user is None:
            if not data.password:
                raise BadRequestError("Set a password for the new login")
            if await self._users.email_taken(email):
                raise ConflictError(f"{email} is already used by another login. Change the employee's email first")
            role_id = data.role_id or (await self._roles.role_by_code(
                employee.organization_id, default_role_code(employee.role))).id
            user = await self._users.add(User(
                organization_id=employee.organization_id, branch_id=employee.branch_id, name=employee.name,
                email=email, password_hash=hash_password(data.password), role=account_kind(10),
                employee_id=employee.id, created_by=actor.user_id))
            await self._roles.assign(user, role_id, scope, actor)      # checks the hierarchy
            message = f"Login created for {employee.name}"
        else:
            if user.id == actor.user_id:
                raise BadRequestError("This is your own login — use Change password instead")
            if user.email != email:      # the employee's email changed → keep the login ID in step
                if await self._users.email_taken(email):
                    raise ConflictError(f"{email} is already used by another login")
                user.email = email
            current = await self._roles.login_role(user.id)
            if current is not None and current.level >= await self._roles.level_of(actor.user_id, actor.is_superadmin):
                raise BadRequestError(f"{employee.name} is a {current.name}: only someone above that level can change "
                                      f"this login")
            new_role = data.role_id and (current is None or data.role_id != current.id)
            changed_access = bool(new_role) or not user.is_active
            if new_role:
                await self._roles.assign(user, data.role_id, scope, actor)
            user.name, user.branch_id, user.is_active = employee.name, employee.branch_id, True
            if data.password:
                user.password_hash = hash_password(data.password)
            if data.password or changed_access:
                await self._users.revoke_sessions(user.id, _now())   # sign in again with the new password / access
            user.updated_by = actor.user_id
            message = (f"Password reset for {employee.name}" if data.password
                       else f"Login updated for {employee.name}")
        await self._users.commit()
        return await self.login_out(employee, user), message

    async def disable_login(self, employee_id: UUID, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        employee = await self._employee(employee_id, scope)
        user = await self._users.get_employee_login(employee.id)
        if user is None or not user.is_active:
            raise BadRequestError(f"{employee.name} has no active login")
        if user.id == actor.user_id:
            raise BadRequestError("You cannot disable your own login")
        current = await self._roles.login_role(user.id)
        if current is not None and current.level >= await self._roles.level_of(actor.user_id, actor.is_superadmin):
            raise BadRequestError(f"{employee.name} is a {current.name}: only someone above that level can disable it")
        await self._disable(user, actor.user_id)
        await self._users.commit()
        return await self.login_out(employee, user)

    async def sync_from_employee(self, employee: Employee, actor_id: UUID | None) -> None:
        """Staff record edited → the login follows its email (login ID) and name. Its access is the role picked for
        the login (Roles & Access), so a job title change doesn't change it. Caller commits."""
        user = await self._users.get_employee_login(employee.id)
        if user is None:
            return
        if employee.email and user.email != employee.email.lower():
            email = employee.email.lower()
            if await self._users.email_taken(email):
                raise ConflictError(f"{email} is already used by another login")
            user.email = email
        user.name = employee.name
        user.updated_by = actor_id

    async def disable_for_employee(self, employee_id: UUID, actor_id: UUID | None) -> None:
        """Terminate → the login stops working. Caller commits."""
        user = await self._users.get_employee_login(employee_id)
        if user is not None and user.is_active:
            await self._disable(user, actor_id)

    async def _disable(self, user: User, actor_id: UUID | None) -> None:
        user.is_active = False
        user.updated_by = actor_id
        await self._users.revoke_sessions(user.id, _now())
