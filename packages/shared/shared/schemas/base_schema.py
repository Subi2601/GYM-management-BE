from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class TessBaseSchema(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=True,
    )


class ResponseEnvelope(BaseModel, Generic[T]):
    """Standard API response wrapper for all endpoints."""
    success: bool = True
    message: str | None = None
    data: T | None = None

    @classmethod
    def ok(cls, data: T = None, message: str | None = None) -> "ResponseEnvelope[T]":
        return cls(success=True, message=message, data=data)

    @classmethod
    def fail(cls, message: str) -> "ResponseEnvelope[None]":
        return cls(success=False, message=message, data=None)


class PaginatedEnvelope(BaseModel, Generic[T]):
    """
    Standard paginated API response.
    Pagination fields (total, page, page_size) sit at the top level alongside data.
    Response shape:
        { success, message, data: [...], total, page, page_size }
    """
    success: bool = True
    message: str | None = None
    data: list[T] = []
    total: int = 0
    page: int = 1
    page_size: int = 20

    @classmethod
    def ok(
        cls,
        data: list[T],
        total: int,
        page: int,
        page_size: int,
        message: str | None = None,
    ) -> "PaginatedEnvelope[T]":
        return cls(success=True, message=message, data=data, total=total, page=page, page_size=page_size)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def build(cls, items: list[T], total: int, page: int, page_size: int) -> "PaginatedResponse[T]":
        import math
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if page_size else 0,
        )


class TimestampMixin(TessBaseSchema):
    created_at: datetime
    updated_at: datetime


class UUIDSchema(TessBaseSchema):
    id: UUID
