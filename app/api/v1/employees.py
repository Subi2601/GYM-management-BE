"""Employee routes — registration + permission decorators only."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.employee_controller import EmployeeController
from app.core.enums import EmployeeRole
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user, get_payroll_access, get_pii_access
from app.schemas.common import SortDir
from app.schemas.employee import (EmployeeCounts, EmployeeCreate, EmployeePayrollUpdate, EmployeeProfileResponse,
                                  EmployeeResponse, EmployeeUpdate, FeedbackCreate, FeedbackCreated, StaffLoginResponse,
                                  StaffLoginSave, TrainerOption)

router = APIRouter(prefix="/api/v1/employees", tags=["employees"])


@router.get("", response_model=PaginatedEnvelope[EmployeeResponse],
            dependencies=[Depends(require_permission("employee:list"))])
async def list_employees(
    pagination: PaginationParams = Depends(get_pagination),
    status: Literal["active", "archive", "all"] = Query(default="active"),
    role: EmployeeRole | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    sort_by: Literal["employee_code", "name", "role", "base_salary", "date_of_joining", "average_rating",
                     "created_at"] | None = Query(default=None),
    sort_dir: SortDir = Query(default="desc"),
    scope: BranchScope = Depends(get_branch_scope),
    show_pii: bool = Depends(get_pii_access),
    controller: EmployeeController = Depends(),
):
    return await controller.list_employees(scope, pagination, status, role, search, sort_by, sort_dir, show_pii)


@router.get("/counts", response_model=ResponseEnvelope[EmployeeCounts],
            dependencies=[Depends(require_permission("employee:list"))])
async def employee_counts(scope: BranchScope = Depends(get_branch_scope),
                          controller: EmployeeController = Depends()):
    return await controller.counts(scope)


@router.get("/trainers", response_model=ResponseEnvelope[list[TrainerOption]],
            dependencies=[Depends(require_permission("employee:list"))])
async def list_trainers(scope: BranchScope = Depends(get_branch_scope),
                        controller: EmployeeController = Depends()):
    return await controller.list_trainers(scope)


@router.get("/{employee_id}", response_model=ResponseEnvelope[EmployeeResponse],
            dependencies=[Depends(require_permission("employee:list"))])
async def get_employee(employee_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                       show_pii: bool = Depends(get_pii_access), controller: EmployeeController = Depends()):
    return await controller.get_employee(employee_id, scope, show_pii)


@router.get("/{employee_id}/profile", response_model=ResponseEnvelope[EmployeeProfileResponse],
            dependencies=[Depends(require_permission("employee:list"))])
async def get_employee_profile(employee_id: UUID,
                               month: int | None = Query(default=None, ge=1, le=12),
                               year: int | None = Query(default=None, ge=2000, le=2100),
                               scope: BranchScope = Depends(get_branch_scope),
                               show_pii: bool = Depends(get_pii_access),
                               show_payroll: bool = Depends(get_payroll_access),
                               controller: EmployeeController = Depends()):
    """Staff details page; `month` / `year` pick the attendance month (default: current)."""
    return await controller.get_profile(employee_id, scope, show_pii, show_payroll, month, year)


@router.post("", response_model=ResponseEnvelope[EmployeeResponse], status_code=201,
             dependencies=[Depends(require_permission("employee:create"))])
async def create_employee(body: EmployeeCreate, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          show_pii: bool = Depends(get_pii_access), controller: EmployeeController = Depends()):
    return await controller.create_employee(body, scope, ctx, show_pii)


@router.put("/{employee_id}", response_model=ResponseEnvelope[EmployeeResponse],
            dependencies=[Depends(require_permission("employee:update"))])
async def update_employee(employee_id: UUID, body: EmployeeUpdate, scope: BranchScope = Depends(get_branch_scope),
                          ctx: RequestContext = Depends(get_current_user),
                          show_pii: bool = Depends(get_pii_access), controller: EmployeeController = Depends()):
    return await controller.update_employee(employee_id, body, scope, ctx, show_pii)


@router.put("/{employee_id}/payroll", response_model=ResponseEnvelope[EmployeeResponse],
            dependencies=[Depends(require_permission("employee:update"))])
async def update_payroll(employee_id: UUID, body: EmployeePayrollUpdate,
                         scope: BranchScope = Depends(get_branch_scope),
                         ctx: RequestContext = Depends(get_current_user),
                         show_pii: bool = Depends(get_pii_access), controller: EmployeeController = Depends()):
    return await controller.update_payroll(employee_id, body, scope, ctx, show_pii)


@router.get("/{employee_id}/login", response_model=ResponseEnvelope[StaffLoginResponse],
            dependencies=[Depends(require_permission("employee:login"))])
async def get_staff_login(employee_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                          controller: EmployeeController = Depends()):
    return await controller.get_login(employee_id, scope)


@router.put("/{employee_id}/login", response_model=ResponseEnvelope[StaffLoginResponse],
            dependencies=[Depends(require_permission("employee:login"))])
async def save_staff_login(employee_id: UUID, body: StaffLoginSave, scope: BranchScope = Depends(get_branch_scope),
                           ctx: RequestContext = Depends(get_current_user), controller: EmployeeController = Depends()):
    """Create the login (password required) or change role / reset password / re-enable it."""
    return await controller.save_login(employee_id, body, scope, ctx)


@router.delete("/{employee_id}/login", response_model=ResponseEnvelope[StaffLoginResponse],
               dependencies=[Depends(require_permission("employee:login"))])
async def disable_staff_login(employee_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                              ctx: RequestContext = Depends(get_current_user),
                              controller: EmployeeController = Depends()):
    return await controller.disable_login(employee_id, scope, ctx)


@router.patch("/{employee_id}/terminate", response_model=ResponseEnvelope[EmployeeResponse],
              dependencies=[Depends(require_permission("employee:terminate"))])
async def terminate_employee(employee_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                             ctx: RequestContext = Depends(get_current_user),
                             show_pii: bool = Depends(get_pii_access), controller: EmployeeController = Depends()):
    return await controller.terminate_employee(employee_id, scope, ctx, show_pii)


@router.post("/{employee_id}/feedback", response_model=ResponseEnvelope[FeedbackCreated], status_code=201,
             dependencies=[Depends(require_permission("feedback:create"))])
async def add_feedback(employee_id: UUID, body: FeedbackCreate, scope: BranchScope = Depends(get_branch_scope),
                       ctx: RequestContext = Depends(get_current_user), controller: EmployeeController = Depends()):
    return await controller.add_feedback(employee_id, body, scope, ctx)
