"""Payroll routes — registration + permission decorators only."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import ResponseEnvelope

from app.controllers.salary_controller import SalaryController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.salary import (SalaryCalculate, SalaryCalculateResponse, SalaryMonthResponse, SalaryPay,
                                SalaryResponse)

router = APIRouter(prefix="/api/v1/salary", tags=["salary"])


@router.get("", response_model=ResponseEnvelope[SalaryMonthResponse],
            dependencies=[Depends(require_permission("salary:list"))])
async def list_salaries(month: int | None = Query(default=None, ge=1, le=12),
                        year: int | None = Query(default=None, ge=2000, le=2100),
                        scope: BranchScope = Depends(get_branch_scope),
                        controller: SalaryController = Depends()):
    return await controller.list_for_month(scope, month, year)


@router.get("/employee/{employee_id}", response_model=ResponseEnvelope[list[SalaryResponse]],
            dependencies=[Depends(require_permission("salary:list"))])
async def employee_salary_history(employee_id: UUID, scope: BranchScope = Depends(get_branch_scope),
                                  controller: SalaryController = Depends()):
    return await controller.employee_history(employee_id, scope)


@router.post("/calculate", response_model=ResponseEnvelope[SalaryCalculateResponse],
             dependencies=[Depends(require_permission("salary:calculate"))])
async def calculate_salary(body: SalaryCalculate, scope: BranchScope = Depends(get_branch_scope),
                           ctx: RequestContext = Depends(get_current_user),
                           controller: SalaryController = Depends()):
    return await controller.calculate(body, scope, ctx)


@router.put("/{salary_id}/pay", response_model=ResponseEnvelope[SalaryResponse],
            dependencies=[Depends(require_permission("salary:pay"))])
async def pay_salary(salary_id: UUID, body: SalaryPay, scope: BranchScope = Depends(get_branch_scope),
                     ctx: RequestContext = Depends(get_current_user), controller: SalaryController = Depends()):
    return await controller.pay(salary_id, body, scope, ctx)
