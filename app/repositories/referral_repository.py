"""DB operations for referrals: monthly reward programs, who referred whom, rewards. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import exists, func, select

from app.core.scope import BranchScope
from app.models.billing import Subscription
from app.models.member import Member
from app.models.referral import ReferralProgram, ReferralReward, ReferralRewardMember, ReferralTier
from app.repositories.base import BaseRepository
from app.repositories.member_repository import MemberRepository


class ReferralRepository(BaseRepository):

    # ── programs ─────────────────────────────────────────────────────────
    async def program(self, organization_id: UUID, month_key: str) -> ReferralProgram | None:
        stmt = self.alive(ReferralProgram, select(ReferralProgram)).where(
            ReferralProgram.organization_id == organization_id, ReferralProgram.month_key == month_key)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def tiers(self, program_id: UUID) -> list[ReferralTier]:
        stmt = (self.alive(ReferralTier, select(ReferralTier)).where(ReferralTier.program_id == program_id)
                .order_by(ReferralTier.min_referrals.asc()))
        return list((await self._db.execute(stmt)).scalars().all())

    async def delete_tiers(self, program_id: UUID) -> None:
        for tier in await self.tiers(program_id):
            await self._db.delete(tier)
        await self._db.flush()

    async def programs(self, organization_id: UUID, limit: int = 12) -> list[ReferralProgram]:
        stmt = (self.alive(ReferralProgram, select(ReferralProgram))
                .where(ReferralProgram.organization_id == organization_id)
                .order_by(ReferralProgram.month_key.desc()).limit(limit))
        return list((await self._db.execute(stmt)).scalars().all())

    async def unsettled_past(self, organization_id: UUID, current_key: str) -> list[ReferralProgram]:
        stmt = self.alive(ReferralProgram, select(ReferralProgram)).where(
            ReferralProgram.organization_id == organization_id, ReferralProgram.month_key < current_key,
            ReferralProgram.settled.is_(False))
        return list((await self._db.execute(stmt.with_for_update())).scalars().all())

    # ── referrals ────────────────────────────────────────────────────────
    async def month_referrals(self, organization_id: UUID, start: date, end: date,
                              branch_ids: tuple[UUID, ...] | None = None) -> list[tuple[UUID, UUID]]:
        """(referrer id, referred id) for people who joined in [start, end] and paid for a plan; referrers limited
        to `branch_ids` when given."""
        referrer = Member.__table__.alias("referrer")
        paid = exists().where(Subscription.member_id == Member.id, Subscription.payment_id.is_not(None),
                              Subscription.is_delete.is_(False))
        stmt = (select(Member.referred_by_id, Member.id)
                .join(referrer, referrer.c.id == Member.referred_by_id)
                .where(Member.organization_id == organization_id, Member.is_delete.is_(False),
                       referrer.c.is_delete.is_(False), Member.joining_date >= start, Member.joining_date <= end,
                       paid))
        if branch_ids is not None:
            stmt = stmt.where(referrer.c.branch_id.in_(branch_ids))
        return [(a, b) for a, b in (await self._db.execute(stmt.order_by(Member.joining_date))).all()]

    async def members_brief(self, ids: list[UUID]) -> dict[UUID, dict]:
        """id → {name, registration_id, phone, branch_id, joining_date, plan_name, plan_end}."""
        if not ids:
            return {}
        latest = MemberRepository(self._db)._latest_membership()
        paid = (exists().where(Subscription.member_id == Member.id, Subscription.payment_id.is_not(None),
                               Subscription.is_delete.is_(False))).label("paid")
        stmt = (select(Member, latest.c.plan_name, latest.c.end_date, paid)
                .outerjoin(latest, latest.c.member_id == Member.id).where(Member.id.in_(ids)))
        return {m.id: {"id": m.id, "name": m.name, "registration_id": m.registration_id, "phone": m.phone,
                       "branch_id": m.branch_id, "organization_id": m.organization_id, "joining_date": m.joining_date,
                       "referred_by_id": m.referred_by_id, "plan_name": plan, "plan_end": end, "paid": bool(is_paid)}
                for m, plan, end, is_paid in (await self._db.execute(stmt)).all()}

    async def children(self, parent_ids: list[UUID], organization_id: UUID) -> list[tuple[UUID, UUID]]:
        """(child id, parent id) — members referred by any of `parent_ids`."""
        if not parent_ids:
            return []
        stmt = (select(Member.id, Member.referred_by_id)
                .where(Member.referred_by_id.in_(parent_ids), Member.organization_id == organization_id,
                       Member.is_delete.is_(False)).order_by(Member.joining_date))
        return [(a, b) for a, b in (await self._db.execute(stmt)).all()]

    async def referral_counts(self, ids: list[UUID]) -> dict[UUID, int]:
        """How many (live) members each of `ids` referred directly."""
        if not ids:
            return {}
        stmt = (select(Member.referred_by_id, func.count(Member.id))
                .where(Member.referred_by_id.in_(ids), Member.is_delete.is_(False)).group_by(Member.referred_by_id))
        return dict((await self._db.execute(stmt)).all())

    async def get_member(self, member_id: UUID, scope: BranchScope) -> Member | None:
        return await self.get_scoped(Member, member_id, scope)

    # ── rewards ──────────────────────────────────────────────────────────
    async def reward_for(self, member_id: UUID, month_key: str) -> ReferralReward | None:
        stmt = self.alive(ReferralReward, select(ReferralReward)).where(
            ReferralReward.member_id == member_id, ReferralReward.month_key == month_key)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def rewards_for_month(self, organization_id: UUID, month_key: str) -> dict[UUID, ReferralReward]:
        stmt = self.alive(ReferralReward, select(ReferralReward)).where(
            ReferralReward.organization_id == organization_id, ReferralReward.month_key == month_key)
        return {r.member_id: r for r in (await self._db.execute(stmt)).scalars().all()}

    async def get_reward(self, reward_id: UUID, scope: BranchScope) -> ReferralReward | None:
        return await self.get_scoped(ReferralReward, reward_id, scope)

    async def list_rewards(self, scope: BranchScope, status: str, search: str | None, *, offset: int,
                           limit: int) -> tuple[list, int]:
        """(reward, member name, registration id, phone)."""
        stmt = (self.scoped(ReferralReward, select(ReferralReward, Member.name, Member.registration_id, Member.phone)
                            .join(Member, Member.id == ReferralReward.member_id), scope)
                .where(ReferralReward.status == status))
        if search:
            p = f"%{search}%"
            stmt = stmt.where(Member.name.ilike(p) | Member.phone.ilike(p) | Member.registration_id.ilike(p))
        stmt = stmt.order_by(ReferralReward.month_key.desc(), ReferralReward.given_on.desc().nulls_last(), Member.name)
        return await self.paginate(stmt, offset=offset, limit=limit)

    async def count_rewards(self, scope: BranchScope) -> dict[str, int]:
        stmt = self.scoped(ReferralReward, select(ReferralReward.status, func.count(ReferralReward.id)), scope)
        return dict((await self._db.execute(stmt.group_by(ReferralReward.status))).all())

    async def counted_members(self, reward_ids: list[UUID]) -> dict[UUID, list[UUID]]:
        if not reward_ids:
            return {}
        stmt = select(ReferralRewardMember.reward_id, ReferralRewardMember.referred_member_id).where(
            ReferralRewardMember.reward_id.in_(reward_ids), ReferralRewardMember.is_delete.is_(False))
        out: dict[UUID, list[UUID]] = {}
        for rid, mid in (await self._db.execute(stmt)).all():
            out.setdefault(rid, []).append(mid)
        return out

    async def member_rewards(self, member_ids: list[UUID]) -> list[ReferralReward]:
        """Rewards earned by any of these members, newest first."""
        if not member_ids:
            return []
        stmt = (self.alive(ReferralReward, select(ReferralReward)).where(ReferralReward.member_id.in_(member_ids))
                .order_by(ReferralReward.month_key.desc()))
        return list((await self._db.execute(stmt)).scalars().all())

    async def counted_in_rewards(self, member_ids: list[UUID]) -> dict[UUID, str]:
        """referred member id → status of the reward they were counted for (GIVEN wins over PENDING)."""
        if not member_ids:
            return {}
        stmt = (select(ReferralRewardMember.referred_member_id, ReferralReward.status)
                .join(ReferralReward, ReferralReward.id == ReferralRewardMember.reward_id)
                .where(ReferralRewardMember.referred_member_id.in_(member_ids), ReferralReward.is_delete.is_(False)))
        out: dict[UUID, str] = {}
        for mid, status in (await self._db.execute(stmt)).all():
            if out.get(mid) != "GIVEN":
                out[mid] = status
        return out
