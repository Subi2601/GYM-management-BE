"""Shared repository helpers — soft-delete + SaaS scope filters. DB operations only, no business logic."""
from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scope import BranchScope

M = TypeVar("M")


class BaseRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def commit(self) -> None:
        await self._db.commit()

    async def rollback(self) -> None:
        await self._db.rollback()

    async def flush(self) -> None:
        await self._db.flush()

    async def add(self, obj: M) -> M:
        self._db.add(obj)
        await self._db.flush()
        return obj

    async def delete(self, obj: Any) -> None:
        await self._db.delete(obj)
        await self._db.flush()

    async def refresh(self, obj: Any) -> None:
        await self._db.refresh(obj)

    @staticmethod
    def alive(model: Any, stmt: Select) -> Select:
        return stmt.where(model.is_delete.is_(False))

    @staticmethod
    def scoped(model: Any, stmt: Select, scope: BranchScope) -> Select:
        """Tenant + branch filter. Every read of business data goes through this."""
        return stmt.where(model.organization_id == scope.organization_id,
                          model.branch_id.in_(scope.branch_ids),
                          model.is_delete.is_(False))

    @staticmethod
    def ordered(stmt: Select, columns: dict[str, ColumnElement], sort_by: str | None, sort_dir: str,
                default: tuple, tie_breaker: ColumnElement) -> Select:
        """Order by a whitelisted column (NULLS LAST, then `tie_breaker` for stable pages); else `default`.
        Only keys of `columns` are ever used — user input never reaches the SQL text."""
        column = columns.get(sort_by) if sort_by else None
        if column is None:
            return stmt.order_by(*default)
        if sort_dir == "asc":
            return stmt.order_by(column.asc().nulls_last(), tie_breaker.asc())
        return stmt.order_by(column.desc().nulls_last(), tie_breaker.desc())

    async def get_scoped(self, model: Any, obj_id: UUID, scope: BranchScope) -> Any | None:
        stmt = self.scoped(model, select(model).where(model.id == obj_id), scope)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def paginate(self, stmt: Select, *, offset: int, limit: int) -> tuple[list[Any], int]:
        total = (await self._db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
        rows = (await self._db.execute(stmt.offset(offset).limit(limit))).all()
        return list(rows), total

    async def count_tabs(self, stmt: Select, tabs: dict[str, ColumnElement[bool] | None]) -> dict[str, int]:
        """Count the rows of a list query once per tab, in ONE query: `COUNT(*) FILTER (WHERE …)` per key.
        `stmt` keeps its joins and scope filters; a `None` condition counts every row (the "all" tab)."""
        columns = [(func.count() if cond is None else func.count().filter(cond)).label(key)
                   for key, cond in tabs.items()]
        counted = stmt.with_only_columns(*columns, maintain_column_froms=True).order_by(None)
        return dict((await self._db.execute(counted)).one()._mapping)

    async def paginate_scalars(self, stmt: Select, *, offset: int, limit: int) -> tuple[list[Any], int]:
        total = (await self._db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))).scalar_one()
        rows = (await self._db.execute(stmt.offset(offset).limit(limit))).scalars().all()
        return list(rows), total
