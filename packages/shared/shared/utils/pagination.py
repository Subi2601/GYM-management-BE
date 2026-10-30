from __future__ import annotations

from fastapi import Query
from pydantic import BaseModel


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def get_pagination(
    page: int = Query(default=1, ge=1),
    # 500 cap lets dropdown/lookup screens fetch a full branch list in one call.
    page_size: int = Query(default=20, ge=1, le=500),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)
