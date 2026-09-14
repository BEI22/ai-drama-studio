"""HTTP middleware: request id assignment + access logging (PRD sections 28, 31)."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.context import reset_context, set_request_id

logger = logging.getLogger("app.request")

# Health probes would otherwise flood the log stream.
_QUIET_PATHS = {"/health", "/api/v1/health", "/favicon.ico", "/openapi.json"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign/propagate ``X-Request-ID`` and log one line per request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        header = settings.request_id_header
        request_id = set_request_id(request.headers.get(header))
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception(
                "request failed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "latency_ms": latency_ms,
                },
            )
            reset_context()
            raise

        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[header] = request_id

        if request.url.path not in _QUIET_PATHS:
            logger.info(
                "request completed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "latency_ms": latency_ms,
                },
            )

        reset_context()
        return response
