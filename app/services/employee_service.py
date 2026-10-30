"""Employees business logic — codes, uniqueness, PII, termination, feedback rating, profile."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.encryption import decrypt_pii, encrypt_pii, mask_pii
from app.core.enums import EmployeeRole, EmployeeStatus
from app.core.scope import BranchScope
from app.models.staff import Employee, EmployeeFeedback
from app.repositories.employee_repository import EmployeeRepository

_PLAIN_FIELDS = ("name", "phone", "email", "address", "role", "education", "experience", "id_proof_type",
                 "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relation",
                 "bank_name", "ifsc_code", "date_of_joining", "status")
# request field → encrypted column
_PII_FIELDS = {"aadhar_number": "aadhar_number_enc", "pan_number": "pan_number_enc",
               "id_proof_number": "id_proof_number_enc", "bank_account_number": "bank_account_number_enc"}
# Fields the original UI requires — a partial update may change them but never clear them.
_NOT_CLEARABLE = {"name", "phone", "email", "address", "role", "id_proof_type", "emergency_contact_name",
                  "emergency_contact_phone", "emergency_contact_relation", "bank_name", "ifsc_code",
                  "date_of_joining", "status", "base_salary", *_PII_FIELDS}

STATUS_FILTERS: dict[str, tuple[EmployeeStatus, ...] | None] = {
    "active": (EmployeeStatus.ACTIVE,),
    "archive": (EmployeeStatus.TERMINATED,),
    "all": None,
}


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _rating(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


class EmployeeService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = EmployeeRepository(db)

    # ── output builders ──────────────────────────────────────────────────
    @staticmethod
    def employee_out(e: Employee, *, show_pii: bool) -> dict:
        def pii(column: str) -> str | None:
            plain = decrypt_pii(getattr(e, column))
            return plain if show_pii else mask_pii(plain)

        return {
            "id": e.id, "branch_id": e.branch_id, "employee_code": e.employee_code,
            "name": e.name, "phone": e.phone, "email": e.email, "address": e.address, "role": e.role,
            "education": e.education, "experience": e.experience,
            **{field: pii(column) for field, column in _PII_FIELDS.items()},
            "id_proof_type": e.id_proof_type,
            "emergency_contact_name": e.emergency_contact_name,
            "emergency_contact_phone": e.emergency_contact_phone,
            "emergency_contact_relation": e.emergency_contact_relation,
            "base_salary": float(e.base_salary or 0), "bank_name": e.bank_name, "ifsc_code": e.ifsc_code,
            "status": e.status, "average_rating": _rating(e.average_rating),
            "date_of_joining": e.date_of_joining, "date_of_termination": e.date_of_termination,
            "created_at": e.created_at, "updated_at": e.updated_at,
        }

    @staticmethod
    def feedback_out(f: EmployeeFeedback) -> dict:
        return {"id": f.id, "employee_id": f.employee_id, "client_name": f.client_name, "rating": f.rating,
                "comment": f.comment, "feedback_date": f.feedback_date,
                "created_at": f.created_at, "updated_at": f.updated_at}

    @staticmethod
    def pt_client_out(pt, member_name: str, plan_name: str | None) -> dict:
        return {"id": pt.id, "member_id": pt.member_id, "member_name": member_name, "plan_id": pt.plan_id,
                "plan_name": plan_name, "goal": pt.goal, "total_sessions": pt.total_sessions,
                "sessions_remaining": pt.sessions_remaining, "start_date": pt.start_date,
                "expiry_date": pt.expiry_date, "status": pt.status, "is_paid": pt.is_paid}

    async def _require(self, employee_id: UUID, scope: BranchScope) -> Employee:
        employee = await self._repo.get_employee(employee_id, scope)
        if employee is None:
            raise NotFoundError("Employee")
        return employee

    # ── queries ──────────────────────────────────────────────────────────
    async def list_employees(self, scope: BranchScope, *, offset: int, limit: int, status_filter: str,
                             role: EmployeeRole | None, search: str | None,
                             show_pii: bool) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_employees(scope, offset=offset, limit=limit,
                                                      statuses=STATUS_FILTERS.get(status_filter),
                                                      role=role, search=search)
        return [self.employee_out(e, show_pii=show_pii) for e in rows], total

    async def get_employee(self, employee_id: UUID, scope: BranchScope, show_pii: bool) -> dict:
        return self.employee_out(await self._require(employee_id, scope), show_pii=show_pii)

    async def get_profile(self, employee_id: UUID, scope: BranchScope, show_pii: bool) -> dict:
        employee = await self._require(employee_id, scope)
        feedbacks = await self._repo.list_feedbacks(employee_id, scope)
        clients = await self._repo.list_pt_clients(employee_id, scope)
        return {
            "employee": self.employee_out(employee, show_pii=show_pii),
            "feedbacks": [self.feedback_out(f) for f in feedbacks],
            "pt_clients": [self.pt_client_out(*row) for row in clients],
            "average_rating": _rating(employee.average_rating),
        }

    async def list_trainers(self, scope: BranchScope) -> list[dict]:
        rows = await self._repo.list_by_status(scope, EmployeeStatus.ACTIVE, role=EmployeeRole.TRAINER)
        return [{"id": e.id, "employee_code": e.employee_code, "name": e.name, "phone": e.phone} for e in rows]

    async def next_employee_code(self, branch_id: UUID) -> str:
        return f"SG-EMP-{await self._repo.last_code_number(branch_id) + 1:03d}"

    # ── commands ─────────────────────────────────────────────────────────
    async def create_employee(self, data, scope: BranchScope, actor: RequestContext, show_pii: bool) -> dict:
        branch_id = scope.require_branch()
        if data.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("A new employee cannot be created as TERMINATED")
        if await self._repo.get_by_phone(branch_id, data.phone):
            raise ConflictError("An employee with this phone number already exists")
        employee = Employee(
            organization_id=scope.organization_id, branch_id=branch_id,
            employee_code=await self.next_employee_code(branch_id),
            **{f: getattr(data, f) for f in _PLAIN_FIELDS},
            base_salary=_money(data.base_salary),
            **{column: encrypt_pii(getattr(data, field)) for field, column in _PII_FIELDS.items()},
            created_by=actor.user_id,
        )
        await self._repo.add(employee)
        await self._repo.commit()
        return await self.get_employee(employee.id, scope, show_pii)

    async def update_employee(self, employee_id: UUID, data, scope: BranchScope, actor: RequestContext,
                              show_pii: bool) -> dict:
        employee = await self._require(employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("A terminated employee cannot be updated")
        sent = {f for f in data.model_fields_set
                if not (getattr(data, f) is None and f in _NOT_CLEARABLE)}
        if "status" in sent and data.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("Use the terminate action to terminate an employee")
        if "phone" in sent and data.phone != employee.phone:
            existing = await self._repo.get_by_phone(employee.branch_id, data.phone)
            if existing and existing.id != employee.id:
                raise ConflictError("An employee with this phone number already exists")
        for field in _PLAIN_FIELDS:
            if field in sent:
                setattr(employee, field, getattr(data, field))
        if "base_salary" in sent:
            employee.base_salary = _money(data.base_salary)
        for field, column in _PII_FIELDS.items():
            if field in sent:
                setattr(employee, column, encrypt_pii(getattr(data, field)))
        employee.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_employee(employee.id, scope, show_pii)

    async def terminate_employee(self, employee_id: UUID, scope: BranchScope, actor: RequestContext,
                                 show_pii: bool) -> dict:
        scope.require_branch()
        employee = await self._require(employee_id, scope)
        if employee.status == EmployeeStatus.TERMINATED:
            raise BadRequestError("Employee is already terminated")
        employee.status = EmployeeStatus.TERMINATED
        employee.date_of_termination = timeutil.today()
        employee.updated_by = actor.user_id
        await self._repo.commit()
        return await self.get_employee(employee.id, scope, show_pii)

    async def add_feedback(self, employee_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        employee = await self._require(employee_id, scope)
        feedback = EmployeeFeedback(
            organization_id=employee.organization_id, branch_id=employee.branch_id, employee_id=employee.id,
            client_name=data.client_name, rating=data.rating, comment=data.comment,
            feedback_date=data.feedback_date or timeutil.today(), created_by=actor.user_id,
        )
        await self._repo.add(feedback)
        employee.average_rating = _rating(await self._repo.average_rating(employee.id, scope))
        employee.updated_by = actor.user_id
        await self._repo.commit()
        return {"feedback": self.feedback_out(feedback), "average_rating": employee.average_rating}
