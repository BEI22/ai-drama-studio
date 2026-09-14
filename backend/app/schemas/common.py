"""Shared Pydantic schemas: the unified response envelope (PRD section 23)."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str = Field(..., examples=["GENERATION_FAILED"])
    message: str = Field(..., examples=["Video generation failed"])
    details: Any | None = None


class Envelope(BaseModel, Generic[T]):
    """Every JSON endpoint returns this shape."""

    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    request_id: str | None = None
    meta: dict[str, Any] | None = None


class PaginationMeta(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
