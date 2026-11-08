"""DB operations for offers. No business logic."""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, or_, select

from app.core.scope import BranchScope
from app.models.billing import Offer
from app.repositories.base import BaseRepository

OFFER_TABS = ("active", "inactive", "all")


def _tab_condition(tab: str | None) -> ColumnElement[bool] | None:
    if tab == "active":
        return Offer.is_active.is_(True)
    if tab == "inactive":
        return Offer.is_active.is_(False)
    return None


def available_condition(today: date) -> ColumnElement[bool]:
    """Switched on and today inside the (optional) date window."""
    return and_(Offer.is_active.is_(True),
                or_(Offer.valid_from.is_(None), Offer.valid_from <= today),
                or_(Offer.valid_to.is_(None), Offer.valid_to >= today))


class OfferRepository(BaseRepository):

    async def list_offers(self, scope: BranchScope, *, offset: int, limit: int, search: str | None,
                          tab: str | None, sort_by: str | None, sort_dir: str) -> tuple[list[Offer], int]:
        stmt = self.scoped(Offer, select(Offer), scope)
        if search:
            stmt = stmt.where(Offer.name.ilike(f"%{search}%"))
        cond = _tab_condition(tab)
        if cond is not None:
            stmt = stmt.where(cond)
        columns = {"name": Offer.name, "discount_percent": Offer.discount_percent, "valid_to": Offer.valid_to,
                   "created_at": Offer.created_at}
        stmt = self.ordered(stmt, columns, sort_by, sort_dir, (Offer.is_active.desc(), Offer.name.asc()), Offer.id)
        return await self.paginate_scalars(stmt, offset=offset, limit=limit)

    async def tab_counts(self, scope: BranchScope) -> dict[str, int]:
        return await self.count_tabs(self.scoped(Offer, select(Offer), scope),
                                     {t: _tab_condition(t) for t in OFFER_TABS})

    async def available(self, scope: BranchScope, today: date) -> list[Offer]:
        stmt = self.scoped(Offer, select(Offer).where(available_condition(today)), scope)
        return list((await self._db.execute(stmt.order_by(Offer.name.asc()))).scalars().all())

    async def get_offer(self, offer_id: UUID, scope: BranchScope) -> Offer | None:
        return await self.get_scoped(Offer, offer_id, scope)

    async def name_taken(self, branch_id: UUID, name: str, exclude_id: UUID | None = None) -> bool:
        stmt = select(Offer.id).where(Offer.branch_id == branch_id, func.lower(Offer.name) == name.lower(),
                                      Offer.is_delete.is_(False))
        if exclude_id:
            stmt = stmt.where(Offer.id != exclude_id)
        return (await self._db.execute(stmt.limit(1))).first() is not None
