"""Shared schema building blocks."""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, model_validator
from shared.schemas.base_schema import TessBaseSchema

# 10-digit Indian mobile number, as validated by the original UI.
Phone = Annotated[str, Field(pattern=r"^\d{10}$", description="10-digit mobile number")]


class FormSchema(TessBaseSchema):
    """Request body base: blank strings from HTML forms become None so optional fields stay optional."""

    @model_validator(mode="before")
    @classmethod
    def _blank_to_none(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: (None if isinstance(v, str) and v.strip() == "" else v) for k, v in data.items()}
        return data


class CodeResponse(TessBaseSchema):
    code: str
