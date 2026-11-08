"""Referral routes — registration + permission decorators only.

View (lists, tree): `referral:list`. Set the monthly reward and hand rewards over: `referral:manage` (manager level).
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from iam_core import RequestContext, require_permission
from shared.schemas.base_schema import PaginatedEnvelope, ResponseEnvelope
from shared.utils.pagination import PaginationParams, get_pagination

from app.controllers.referral_controller import ReferralController
from app.core.scope import BranchScope
from app.dependencies import get_branch_scope, get_current_user
from app.schemas.referral import (EligibleList, GiveIn, GiveOut, ProgramIn, ProgramOut, ReferralCounts,
                                  ReferralStatus, ReferralTree, RewardRow)

router = APIRouter(prefix="/api/v1/referrals", tags=["referrals"])
_LIST = [Depends(require_permission("referral:list"))]
_MANAGE = [Depends(require_permission("referral:manage"))]


@router.get("/status", response_model=ResponseEnvelope[ReferralStatus], dependencies=_LIST)
async def referral_status(scope: BranchScope = Depends(get_branch_scope), controller: ReferralController = Depends()):
    """This month's (and next month's) reward; `is_set` false = no reward this month."""
    return await controller.status(scope)


@router.get("/programs", response_model=ResponseEnvelope[list[ProgramOut]], dependencies=_LIST)
async def referral_programs(scope: BranchScope = Depends(get_branch_scope), controller: ReferralController = Depends()):
    return await controller.programs(scope)


@router.put("/program", response_model=ResponseEnvelope[ProgramOut], dependencies=_MANAGE)
async def set_referral_program(body: ProgramIn, scope: BranchScope = Depends(get_branch_scope),
                               ctx: RequestContext = Depends(get_current_user),
                               controller: ReferralController = Depends()):
    """Set / replace a month's reward tiers (gym-wide)."""
    return await controller.set_program(body, scope, ctx)


@router.get("/eligible", response_model=ResponseEnvelope[EligibleList], dependencies=_LIST)
async def eligible(scope: BranchScope = Depends(get_branch_scope), controller: ReferralController = Depends()):
    """This month's referrers, their count and the reward reached."""
    return await controller.eligible(scope)


@router.get("/rewards", response_model=PaginatedEnvelope[RewardRow], dependencies=_LIST)
async def rewards(pagination: PaginationParams = Depends(get_pagination),
                  status: Literal["PENDING", "GIVEN"] = Query(default="PENDING"),
                  search: str | None = Query(default=None, max_length=100),
                  scope: BranchScope = Depends(get_branch_scope), controller: ReferralController = Depends()):
    return await controller.rewards(scope, pagination, status, search)


@router.get("/counts", response_model=ResponseEnvelope[ReferralCounts], dependencies=_LIST)
async def referral_counts(scope: BranchScope = Depends(get_branch_scope), controller: ReferralController = Depends()):
    return await controller.counts(scope)


@router.post("/give", response_model=ResponseEnvelope[GiveOut], dependencies=_MANAGE)
async def give_reward(body: GiveIn, scope: BranchScope = Depends(get_branch_scope),
                      ctx: RequestContext = Depends(get_current_user), controller: ReferralController = Depends()):
    return await controller.give(body, scope, ctx)


@router.get("/tree/{member_id}", response_model=ResponseEnvelope[ReferralTree], dependencies=_LIST)
async def referral_tree(member_id: UUID, levels: int = Query(default=1, ge=1, le=8),
                        scope: BranchScope = Depends(get_branch_scope), controller: ReferralController = Depends()):
    """The member's referrals (direct only by default; `levels` for deeper), their plans and reward state, plus the
    member's rewards."""
    return await controller.tree(member_id, scope, levels)
