"""Employees request/response handling — no business logic (EmployeeService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EmployeeRole
from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.employee import (EmployeeCounts, EmployeeCreate, EmployeePayrollUpdate, EmployeeProfileResponse,
                                  EmployeeResponse, EmployeeUpdate, FeedbackCreate, FeedbackCreated, StaffLoginResponse,
                                  StaffLoginSave, TrainerOption)
from app.services.employee_service import EmployeeService
from app.services.staff_login_service import StaffLoginService


class EmployeeController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = EmployeeService(db)
        self._logins = StaffLoginService(db)

    async def get_login(self, employee_id: UUID, scope: BranchScope) -> ResponseEnvelope[StaffLoginResponse]:
        return ResponseEnvelope.ok(StaffLoginResponse(**await self._logins.get_login(employee_id, scope)))

    async def save_login(self, employee_id: UUID, body: StaffLoginSave, scope: BranchScope,
                         ctx: RequestContext) -> ResponseEnvelope[StaffLoginResponse]:
        data, message = await self._logins.save_login(employee_id, body, scope, ctx)
        return ResponseEnvelope.ok(StaffLoginResponse(**data), message=message)

    async def disable_login(self, employee_id: UUID, scope: BranchScope,
                            ctx: RequestContext) -> ResponseEnvelope[StaffLoginResponse]:
        data = await self._logins.disable_login(employee_id, scope, ctx)
        return ResponseEnvelope.ok(StaffLoginResponse(**data), message="Login disabled")

    async def list_employees(self, scope: BranchScope, pagination: PaginationParams, status_filter: str,
                             role: EmployeeRole | None, search: str | None, sort_by: str | None,
                             sort_dir: str, show_pii: bool) -> PaginatedEnvelope[EmployeeResponse]:
        rows, total = await self._service.list_employees(
            scope, offset=pagination.offset, limit=pagination.limit, status_filter=status_filter,
            role=role, search=search, sort_by=sort_by, sort_dir=sort_dir, show_pii=show_pii)
        return PaginatedEnvelope.ok([EmployeeResponse(**r) for r in rows], total,
                                   pagination.page, pagination.page_size)

    async def counts(self, scope: BranchScope) -> ResponseEnvelope[EmployeeCounts]:
        return ResponseEnvelope.ok(EmployeeCounts(**await self._service.status_counts(scope)))

    async def list_trainers(self, scope: BranchScope) -> ResponseEnvelope[list[TrainerOption]]:
        return ResponseEnvelope.ok([TrainerOption(**t) for t in await self._service.list_trainers(scope)])

    async def get_employee(self, employee_id: UUID, scope: BranchScope,
                           show_pii: bool) -> ResponseEnvelope[EmployeeResponse]:
        return ResponseEnvelope.ok(EmployeeResponse(**await self._service.get_employee(employee_id, scope,
                                                                                      show_pii)))

    async def get_profile(self, employee_id: UUID, scope: BranchScope, show_pii: bool, show_payroll: bool,
                          month: int | None, year: int | None) -> ResponseEnvelope[EmployeeProfileResponse]:
        data = await self._service.get_profile(employee_id, scope, show_pii=show_pii, show_payroll=show_payroll,
                                               month=month, year=year)
        return ResponseEnvelope.ok(EmployeeProfileResponse(**data))

    async def create_employee(self, body: EmployeeCreate, scope: BranchScope, ctx: RequestContext,
                              show_pii: bool) -> ResponseEnvelope[EmployeeResponse]:
        data = await self._service.create_employee(body, scope, ctx, show_pii)
        return ResponseEnvelope.ok(EmployeeResponse(**data), message="Employee added")

    async def update_employee(self, employee_id: UUID, body: EmployeeUpdate, scope: BranchScope,
                              ctx: RequestContext, show_pii: bool) -> ResponseEnvelope[EmployeeResponse]:
        data = await self._service.update_employee(employee_id, body, scope, ctx, show_pii)
        return ResponseEnvelope.ok(EmployeeResponse(**data), message="Employee updated")

    async def update_payroll(self, employee_id: UUID, body: EmployeePayrollUpdate, scope: BranchScope,
                             ctx: RequestContext, show_pii: bool) -> ResponseEnvelope[EmployeeResponse]:
        data = await self._service.update_payroll(employee_id, body, scope, ctx, show_pii)
        return ResponseEnvelope.ok(EmployeeResponse(**data), message="Payroll details updated")

    async def terminate_employee(self, employee_id: UUID, scope: BranchScope, ctx: RequestContext,
                                 show_pii: bool) -> ResponseEnvelope[EmployeeResponse]:
        data = await self._service.terminate_employee(employee_id, scope, ctx, show_pii)
        return ResponseEnvelope.ok(EmployeeResponse(**data), message="Employee terminated")

    async def add_feedback(self, employee_id: UUID, body: FeedbackCreate, scope: BranchScope,
                           ctx: RequestContext) -> ResponseEnvelope[FeedbackCreated]:
        data = await self._service.add_feedback(employee_id, body, scope, ctx)
        return ResponseEnvelope.ok(FeedbackCreated(**data), message="Feedback added")
