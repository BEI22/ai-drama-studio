"""Unified API response envelope (PRD section 23).

Success::

    {"success": true, "data": {...}, "error": null, "request_id": "req_x"}

Failure::

    {"success": false, "data": null,
     "error": {"code": "GENERATION_FAILED", "message": "..."},
     "request_id": "req_x"}
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from app.core.context import get_request_id


def build_envelope(
    data: Any = None,
    *,
    error: dict[str, Any] | None = None,
    request_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the envelope dict used by every JSON endpoint."""
    payload: dict[str, Any] = {
        "success": error is None,
        "data": None if error is not None else data,
        "error": error,
        "request_id": request_id or get_request_id(),
    }
    if meta is not None:
        payload["meta"] = meta
    return payload


def ok(data: Any = None, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Success envelope (returned directly from route handlers)."""
    return build_envelope(data, meta=meta)


def fail(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    details: Any = None,
    request_id: str | None = None,
) -> JSONResponse:
    """Failure envelope as a ready-to-return :class:`JSONResponse`."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(error=error, request_id=request_id),
    )
