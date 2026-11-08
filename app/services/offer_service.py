"""Offers business logic — the discount master billing screens pick from (festival, referral, …)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from iam_core import RequestContext
from shared.exceptions.http_exceptions import BadRequestError, ConflictError, NotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timeutil
from app.core.enums import MEMBERSHIP_PLAN_TYPES
from app.core.scope import BranchScope
from app.models.billing import Offer
from app.repositories.offer_repository import OfferRepository

_FIELDS = ("name", "discount_percent", "valid_from", "valid_to", "description", "is_active")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def bonus_parts(o: Offer) -> list[str]:
    """What the offer gives besides money off: "+1 month", "+15 days", "Free Protein shaker"."""
    parts = []
    if o.extra_months:
        parts.append(f"+{_plural(o.extra_months, 'month')}")
    if o.extra_days:
        parts.append(f"+{_plural(o.extra_days, 'day')}")
    if o.free_item:
        parts.append(f"Free {o.free_item}")
    return parts


def offer_summary(o: Offer) -> str:
    pct = [f"{o.discount_percent.normalize():f}% off"] if o.discount_percent else []
    return " · ".join(pct + bonus_parts(o))


def extend_end(end: date, o: Offer) -> date:
    """End date with the offer's extra months (calendar) and days."""
    if o.extra_months:
        y, m = divmod(end.month - 1 + o.extra_months, 12)
        year, month = end.year + y, m + 1
        end = date(year, month, min(end.day, calendar.monthrange(year, month)[1]))
    return end + timedelta(days=o.extra_days)


class OfferService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = OfferRepository(db)

    @staticmethod
    def offer_out(o: Offer) -> dict:
        today = timeutil.today()
        available = (o.is_active and (o.valid_from is None or o.valid_from <= today)
                     and (o.valid_to is None or o.valid_to >= today))
        return {"id": o.id, "name": o.name, "discount_percent": float(o.discount_percent),
                "extra_months": o.extra_months, "extra_days": o.extra_days, "free_item": o.free_item,
                "summary": offer_summary(o),
                "valid_from": o.valid_from, "valid_to": o.valid_to, "description": o.description,
                "is_active": o.is_active, "available": available, "category_ids": list(o.category_ids or []),
                "created_at": o.created_at, "updated_at": o.updated_at}

    async def apply_bonus(self, offer_id: UUID | None, lines: list, scope: BranchScope) -> str | None:
        """After billing with an offer: add its extra time to the membership `lines` [(subscription, plan,
        applies)] it covers, and return the bonus text for the payment / invoice (None = money off only)."""
        if offer_id is None:
            return None
        offer = await self._get(offer_id, scope)
        if offer.extra_months or offer.extra_days:
            for sub, plan, applies in lines:
                if applies and plan.type in MEMBERSHIP_PLAN_TYPES:
                    sub.end_date = extend_end(sub.end_date, offer)
        parts = bonus_parts(offer)
        return f"{offer.name}: {', '.join(parts)}"[:250] if parts else None

    # ── queries ──────────────────────────────────────────────────────────
    async def list_offers(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                          tab: str | None, sort_by: str | None, sort_dir: str) -> tuple[list[dict], int]:
        rows, total = await self._repo.list_offers(scope, offset=offset, limit=limit, search=search, tab=tab,
                                                   sort_by=sort_by, sort_dir=sort_dir)
        return [self.offer_out(o) for o in rows], total

    async def tab_counts(self, scope: BranchScope) -> dict:
        return await self._repo.tab_counts(scope)

    async def available(self, scope: BranchScope) -> list[dict]:
        return [self.offer_out(o) for o in await self._repo.available(scope, timeutil.today())]

    async def discount_for(self, offer_id: UUID, lines: list[tuple[UUID, Decimal]],
                           scope: BranchScope) -> tuple[Decimal, str, list[bool]]:
        """For billing `lines` = [(plan category, line price)]: (discount, reason, which lines it applies to).
        The % applies only to lines in the offer's categories (every line when it has none). Refused once the
        offer is switched off, outside its dates, or fits none of the plans — so the % can't be bent on the way."""
        offer = await self._get(offer_id, scope)
        today = timeutil.today()
        if not (offer.is_active and (offer.valid_from is None or offer.valid_from <= today)
                and (offer.valid_to is None or offer.valid_to >= today)):
            raise BadRequestError(f"The offer '{offer.name}' is no longer available. Pick another offer")
        cats = set(offer.category_ids or [])
        applies = [not cats or category in cats for category, _ in lines]
        eligible = sum((price for (_, price), ok in zip(lines, applies) if ok), Decimal(0))
        if eligible <= 0:
            raise BadRequestError(f"The offer '{offer.name}' doesn't apply to the selected plans")
        discount = (eligible * offer.discount_percent / Decimal(100)).quantize(Decimal("0.01"))
        reason = f"{offer.name} ({offer.discount_percent.normalize():f}%)" if offer.discount_percent else offer.name
        return discount, reason, applies

    async def _get(self, offer_id: UUID, scope: BranchScope) -> Offer:
        offer = await self._repo.get_offer(offer_id, scope)
        if offer is None:
            raise NotFoundError("Offer")
        return offer

    # ── commands ─────────────────────────────────────────────────────────
    @staticmethod
    def _check_window(valid_from, valid_to) -> None:
        if valid_from and valid_to and valid_from > valid_to:
            raise BadRequestError("Valid to must be on or after valid from")

    async def create_offer(self, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        self._check_window(data.valid_from, data.valid_to)
        name = data.name.strip()
        if await self._repo.name_taken(branch_id, name):
            raise ConflictError(f"An offer named '{name}' already exists")
        offer = await self._repo.add(Offer(
            organization_id=scope.organization_id, branch_id=branch_id, name=name,
            discount_percent=Decimal(str(data.discount_percent)), extra_months=data.extra_months,
            extra_days=data.extra_days, free_item=(data.free_item or "").strip() or None, valid_from=data.valid_from,
            valid_to=data.valid_to, description=data.description, is_active=data.is_active,
            category_ids=list(dict.fromkeys(data.category_ids or [])), created_by=actor.user_id))
        await self._repo.commit()
        return self.offer_out(offer)

    async def update_offer(self, offer_id: UUID, data, scope: BranchScope, actor: RequestContext) -> dict:
        branch_id = scope.require_branch()
        offer = await self._get(offer_id, scope)
        sent = data.model_fields_set
        valid_from = data.valid_from if "valid_from" in sent else offer.valid_from
        valid_to = data.valid_to if "valid_to" in sent else offer.valid_to
        self._check_window(valid_from, valid_to)
        if "name" in sent and data.name:
            name = data.name.strip()
            if await self._repo.name_taken(branch_id, name, exclude_id=offer.id):
                raise ConflictError(f"An offer named '{name}' already exists")
            offer.name = name
        if "discount_percent" in sent and data.discount_percent is not None:
            offer.discount_percent = Decimal(str(data.discount_percent))
        if "extra_months" in sent and data.extra_months is not None:
            offer.extra_months = data.extra_months
        if "extra_days" in sent and data.extra_days is not None:
            offer.extra_days = data.extra_days
        if "free_item" in sent:
            offer.free_item = (data.free_item or "").strip() or None
        if not (offer.discount_percent or offer.extra_months or offer.extra_days or offer.free_item):
            raise BadRequestError("An offer needs a % off, extra time or a free item")
        if "is_active" in sent and data.is_active is not None:
            offer.is_active = data.is_active
        offer.valid_from, offer.valid_to = valid_from, valid_to
        if "description" in sent:
            offer.description = data.description
        if "category_ids" in sent:
            offer.category_ids = list(dict.fromkeys(data.category_ids or []))
        offer.updated_by = actor.user_id
        await self._repo.commit()
        return self.offer_out(offer)

    async def set_status(self, offer_id: UUID, is_active: bool, scope: BranchScope, actor: RequestContext) -> dict:
        scope.require_branch()
        offer = await self._get(offer_id, scope)
        offer.is_active = is_active
        offer.updated_by = actor.user_id
        await self._repo.commit()
        return self.offer_out(offer)
