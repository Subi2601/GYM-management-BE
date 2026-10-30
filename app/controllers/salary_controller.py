"""Payroll request/response handling — no business logic (SalaryService)."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from iam_core import RequestContext
from shared.schemas.base_schema import ResponseEnvelope
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope
from app.dependencies import get_db
from app.schemas.salary import (SalaryCalculate, SalaryCalculateResponse, SalaryMonthResponse, SalaryPay,
                                SalaryResponse)
from app.services.salary_service import SalaryService


class SalaryController:
    def __init__(self, db: AsyncSession = Depends(get_db)) -> None:
        self._service = SalaryService(db)

    async def list_for_month(self, scope: BranchScope, month: int | None,
                             year: int | None) -> ResponseEnvelope[SalaryMonthResponse]:
        return ResponseEnvelope.ok(SalaryMonthResponse(**await self._service.list_for_month(scope, month, year)))

    async def employee_history(self, employee_id: UUID,
                               scope: BranchScope) -> ResponseEnvelope[list[SalaryResponse]]:
        rows = await self._service.employee_history(employee_id, scope)
        return ResponseEnvelope.ok([SalaryResponse(**r) for r in rows])

    async def calculate(self, body: SalaryCalculate, scope: BranchScope,
                        ctx: RequestContext) -> ResponseEnvelope[SalaryCalculateResponse]:
        data = await self._service.calculate(body, scope, ctx)
        message = f"Salary calculated for {data['calculated']} employee(s)"
        if data["skipped_paid"]:
            message += f"; {data['skipped_paid']} already paid, skipped"
        return ResponseEnvelope.ok(SalaryCalculateResponse(**data), message=message)

    async def pay(self, salary_id: UUID, body: SalaryPay, scope: BranchScope,
                  ctx: RequestContext) -> ResponseEnvelope[SalaryResponse]:
        data = await self._service.pay(salary_id, body, scope, ctx)
        return ResponseEnvelope.ok(SalaryResponse(**data), message="Salary marked as paid")
