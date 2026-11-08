"""Referral rewards — a reward plan per calendar month, earned by how many people a member referred that month.

Rules:
- A referral counts in the month the referred member joined, once they have paid for a plan.
- The admin sets each month's reward as tiers (refer ≥ N → reward); the highest tier reached is the reward. A month's
  reward works only in that month: on the 1st the new month has no reward until the admin sets one (the desk sees
  "contact admin"). Months can be set in advance.
- When a month ends, every referrer who reached a tier gets a PENDING reward (written once, the first time anyone
  looks after the month ended). The desk hands rewards over at month end (GIVEN); a reward can also be given during
  its own month. One reward per member per month, recording the referred members it was earned for.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.scope import BranchScope
from app.models.referral import ReferralProgram, ReferralReward, ReferralRewardMember, ReferralTier
from app.repositories.referral_repository import ReferralRepository

TREE_DEPTH = 8                     # levels below the member shown in the tree
GIVEN, PENDING = "GIVEN", "PENDING"


def month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def month_bounds(key: str) -> tuple[date, date]:
    year, month = int(key[:4]), int(key[5:7])
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_label(key: str) -> str:
    return f"{calendar.month_name[int(key[5:7])]} {key[:4]}"


def tier_for(tiers: list[ReferralTier], count: int) -> ReferralTier | None:
    reached = [t for t in tiers if t.min_referrals <= count]
    return max(reached, key=lambda t: t.min_referrals) if reached else None


def next_tier(tiers: list[ReferralTier], count: int) -> ReferralTier | None:
    above = [t for t in tiers if t.min_referrals > count]
    return min(above, key=lambda t: t.min_referrals) if above else None


class ReferralService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = ReferralRepository(db)

    # ── programs ─────────────────────────────────────────────────────────
    async def _program_out(self, program: ReferralProgram | None, key: str) -> dict:
        tiers = await self._repo.tiers(program.id) if program else []
        return {"month_key": key, "month_label": month_label(key), "is_set": program is not None,
                "title": program.title if program else None, "notes": program.notes if program else None,
                "tiers": [{"min_referrals": t.min_referrals, "reward": t.reward} for t in tiers]}

    async def status(self, scope: BranchScope) -> dict:
        await self._settle(scope.organization_id)
        today = timeutil.today()
        key = month_key(today)
        current = await self._repo.program(scope.organization_id, key)
        nxt = month_key(date(today.year + (today.month == 12), today.month % 12 + 1, 1))
        return {"current": await self._program_out(current, key),
                "next": await self._program_out(await self._repo.program(scope.organization_id, nxt), nxt),
                "days_left": (month_bounds(key)[1] - today).days}

    async def programs(self, scope: BranchScope) -> list[dict]:
        return [await self._program_out(p, p.month_key) for p in await self._repo.programs(scope.organization_id)]

    async def set_program(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        current = month_key(timeutil.today())
        if data.month_key < current:
            raise BadRequestError("That month is over. Set the reward for this month or a coming month")
        mins = [t.min_referrals for t in data.tiers]
        if len(set(mins)) != len(mins):
            raise BadRequestError("Each tier needs a different number of referrals")
        program = await self._repo.program(scope.organization_id, data.month_key)
        if program is None:
            program = await self._repo.add(ReferralProgram(organization_id=scope.organization_id,
                                                           month_key=data.month_key, created_by=actor.user_id))
        else:
            await self._repo.delete_tiers(program.id)
            program.updated_by = actor.user_id
        program.title = (data.title or "").strip() or None
        program.notes = (data.notes or "").strip() or None
        for t in sorted(data.tiers, key=lambda x: x.min_referrals):
            await self._repo.add(ReferralTier(program_id=program.id, min_referrals=t.min_referrals,
                                              reward=t.reward.strip(), created_by=actor.user_id))
        await self._repo.commit()
        return await self._program_out(program, program.month_key)

    # ── month end ────────────────────────────────────────────────────────
    async def _settle(self, organization_id: UUID) -> None:
        """Ended months: write PENDING rewards for everyone who reached a tier and has none yet. Runs once per month."""
        programs = await self._repo.unsettled_past(organization_id, month_key(timeutil.today()))
        for program in programs:
            tiers = await self._repo.tiers(program.id)
            start, end = month_bounds(program.month_key)
            existing = await self._repo.rewards_for_month(organization_id, program.month_key)
            by_referrer: dict[UUID, list[UUID]] = defaultdict(list)
            for referrer, referred in await self._repo.month_referrals(organization_id, start, end):
                by_referrer[referrer].append(referred)
            briefs = await self._repo.members_brief(list(by_referrer))
            for referrer, referred in by_referrer.items():
                tier = tier_for(tiers, len(referred))
                if tier is None or referrer in existing or referrer not in briefs:
                    continue
                await self._add_reward(briefs[referrer], program, tier, referred, PENDING, None)
            program.settled = True
        if programs:
            await self._repo.commit()

    async def _add_reward(self, member: dict, program: ReferralProgram, tier: ReferralTier, referred: list[UUID],
                          status: str, actor: RequestContext | None, note: str | None = None) -> ReferralReward:
        reward = await self._repo.add(ReferralReward(
            organization_id=member["organization_id"], branch_id=member["branch_id"], member_id=member["id"],
            program_id=program.id, month_key=program.month_key, referral_count=len(referred), reward=tier.reward,
            status=status, given_on=timeutil.today() if status == GIVEN else None,
            given_by=actor.user_id if actor and status == GIVEN else None, note=note,
            created_by=actor.user_id if actor else None))
        for mid in referred:
            await self._repo.add(ReferralRewardMember(reward_id=reward.id, referred_member_id=mid))
        return reward

    # ── this month ───────────────────────────────────────────────────────
    async def _this_month(self, scope: BranchScope, all_branches: bool = False) -> tuple[
            str, ReferralProgram | None, list[ReferralTier], dict[UUID, list[UUID]]]:
        """(month key, program, tiers, referrer → referred this month) for referrers in scope (or the whole gym)."""
        key = month_key(timeutil.today())
        program = await self._repo.program(scope.organization_id, key)
        tiers = await self._repo.tiers(program.id) if program else []
        start, end = month_bounds(key)
        by_referrer: dict[UUID, list[UUID]] = defaultdict(list)
        branches = None if all_branches else tuple(scope.branch_ids)
        for referrer, referred in await self._repo.month_referrals(scope.organization_id, start, end, branches):
            by_referrer[referrer].append(referred)
        return key, program, tiers, by_referrer

    async def eligible(self, scope: BranchScope) -> dict:
        """Referrers this month: their count, the reward reached (or the next one to aim for), and whether it's given."""
        await self._settle(scope.organization_id)
        key, program, tiers, by_referrer = await self._this_month(scope)
        given = await self._repo.rewards_for_month(scope.organization_id, key)
        people = await self._repo.members_brief(list(by_referrer) + [m for ms in by_referrer.values() for m in ms])
        rows = []
        for referrer, referred in by_referrer.items():
            count = len(referred)
            tier, nxt = tier_for(tiers, count), next_tier(tiers, count)
            reward = given.get(referrer)
            rows.append({**self._brief(people[referrer]), "referral_count": count,
                         "reward": reward.reward if reward else tier.reward if tier else None,
                         "eligible": tier is not None, "given": reward is not None and reward.status == GIVEN,
                         "next_reward": nxt.reward if nxt else None,
                         "needed_for_next": nxt.min_referrals - count if nxt else None,
                         "referred": [self._brief(people[m]) for m in referred]})
        rows.sort(key=lambda r: (not r["eligible"], r["given"], -r["referral_count"], r["name"]))
        return {"month_key": key, "month_label": month_label(key), "is_set": program is not None, "rows": rows}

    @staticmethod
    def _brief(p: dict) -> dict:
        return {"member_id": p["id"], "name": p["name"], "registration_id": p["registration_id"], "phone": p["phone"],
                "plan_name": p["plan_name"], "plan_end": p["plan_end"], "joining_date": p["joining_date"]}

    # ── rewards ──────────────────────────────────────────────────────────
    async def _reward_rows(self, rewards: list[tuple]) -> list[dict]:
        counted = await self._repo.counted_members([r[0].id for r in rewards])
        people = await self._repo.members_brief([m for ms in counted.values() for m in ms])
        return [{"id": r.id, "member_id": r.member_id, "name": name, "registration_id": reg, "phone": phone,
                 "month_key": r.month_key, "month_label": month_label(r.month_key), "referral_count": r.referral_count,
                 "reward": r.reward, "status": r.status, "given_on": r.given_on, "note": r.note,
                 "referred": [self._brief(people[m]) for m in counted.get(r.id, []) if m in people]}
                for r, name, reg, phone in rewards]

    async def rewards(self, scope: BranchScope, status: str, search: str | None, *, offset: int,
                      limit: int) -> tuple[list[dict], int]:
        await self._settle(scope.organization_id)
        rows, total = await self._repo.list_rewards(scope, status, search, offset=offset, limit=limit)
        return await self._reward_rows(rows), total

    async def counts(self, scope: BranchScope) -> dict:
        eligible = await self.eligible(scope)
        by_status = await self._repo.count_rewards(scope)
        return {"eligible": sum(1 for r in eligible["rows"] if r["eligible"] and not r["given"]),
                "pending": by_status.get(PENDING, 0), "rewarded": by_status.get(GIVEN, 0)}

    async def give(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        """Hand over a member's reward: a PENDING one from an ended month, or this month's (needs this month's
        reward set)."""
        scope.require_branch()
        member = await self._repo.get_member(data.member_id, scope)
        if member is None:
            raise NotFoundError("Member")
        today = timeutil.today()
        key = data.month_key or month_key(today)
        reward = await self._repo.reward_for(member.id, key)
        if reward is not None:
            if reward.status == GIVEN:
                raise ConflictError(f"{member.name}'s {month_label(key)} reward was already given on "
                                    f"{reward.given_on:%d-%m-%Y}")
            reward.status, reward.given_on, reward.given_by = GIVEN, today, actor.user_id
            reward.note = (data.note or "").strip() or reward.note
            reward.updated_by = actor.user_id
        else:
            if key != month_key(today):
                raise BadRequestError(f"{member.name} has no reward for {month_label(key)}")
            _, program, tiers, by_referrer = await self._this_month(
                BranchScope(scope.organization_id, member.branch_id, (member.branch_id,)))
            if program is None:
                raise BadRequestError(f"No referral reward is set for {month_label(key)}. Contact the admin to set it")
            referred = by_referrer.get(member.id, [])
            tier = tier_for(tiers, len(referred))
            if tier is None:
                raise BadRequestError(f"{member.name} has {len(referred)} referral(s) this month, not enough for a "
                                      "reward yet")
            brief = (await self._repo.members_brief([member.id]))[member.id]
            reward = await self._add_reward(brief, program, tier, referred, GIVEN, actor, (data.note or "").strip() or None)
        await self._repo.commit()
        return {"member_id": member.id, "name": member.name, "reward": reward.reward,
                "month_label": month_label(reward.month_key)}

    # ── tree ─────────────────────────────────────────────────────────────
    async def tree(self, member_id: UUID, scope: BranchScope, levels: int = 1) -> dict:
        """The member and the people they referred — direct referrals only by default (rewards count only those);
        `levels` > 1 also walks further down (up to TREE_DEPTH)."""
        root = await self._repo.get_member(member_id, scope)
        if root is None:
            raise NotFoundError("Member")
        await self._settle(scope.organization_id)
        org = root.organization_id
        children: dict[UUID, list[UUID]] = defaultdict(list)
        level, seen = [root.id], {root.id}
        for _ in range(min(levels, TREE_DEPTH)):
            pairs = [(c, p) for c, p in await self._repo.children(level, org) if c not in seen]
            if not pairs:
                break
            for child, parent in pairs:
                children[parent].append(child)
                seen.add(child)
            level = [c for c, _ in pairs]
        ids = list(seen)
        people = await self._repo.members_brief(ids + ([root.referred_by_id] if root.referred_by_id else []))

        # Colours: got a reward / reward due (pending or reached this month) / counted for someone's reward.
        rewards = await self._repo.member_rewards(ids)
        got = {r.member_id for r in rewards if r.status == GIVEN}
        due = {r.member_id for r in rewards if r.status == PENDING}
        counted = await self._repo.counted_in_rewards(ids)
        key, program, tiers, by_referrer = await self._this_month(scope, all_branches=True)
        given_now = await self._repo.rewards_for_month(org, key)
        for referrer, referred in by_referrer.items():
            if tier_for(tiers, len(referred)) is not None and referrer not in given_now:
                due.add(referrer)
                for m in referred:
                    counted.setdefault(m, PENDING)

        direct_counts = await self._repo.referral_counts(ids)

        def node(mid: UUID) -> dict:
            p = people[mid]
            return {**self._brief(p), "referral_count": direct_counts.get(mid, 0), "paid": p["paid"],
                    "rewarded": mid in got, "reward_due": mid in due, "counted": mid in counted,
                    "counted_status": counted.get(mid),
                    "children": [node(c) for c in children.get(mid, []) if c in people]}

        mine = [r for r in rewards if r.member_id == root.id]
        counted_by = await self._repo.counted_members([r.id for r in mine])
        names = await self._repo.members_brief([m for ms in counted_by.values() for m in ms])
        return {
            "root": node(root.id),
            "referred_by": self._brief(people[root.referred_by_id]) if root.referred_by_id in people else None,
            "total_referred": len(ids) - 1,
            "rewards": [{"id": r.id, "month_key": r.month_key, "month_label": month_label(r.month_key),
                         "reward": r.reward, "status": r.status, "given_on": r.given_on,
                         "referral_count": r.referral_count, "note": r.note,
                         "referred": [self._brief(names[m]) for m in counted_by.get(r.id, []) if m in names]}
                        for r in mine],
        }
