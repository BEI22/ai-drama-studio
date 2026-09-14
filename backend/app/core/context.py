"""Request-scoped context (request_id / task_id propagation).

Uses :mod:`contextvars` so that the request id is available to the logging
filter, the response envelope builder and any nested service call without
threading it through every signature.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER_DEFAULT = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)


def generate_request_id() -> str:
    """Return a new short request id, e.g. ``req_9f2c1a4b7d3e5f60``."""
    return f"req_{uuid.uuid4().hex[:16]}"


def set_request_id(value: str | None) -> str:
    request_id = value or generate_request_id()
    _request_id.set(request_id)
    return request_id


def get_request_id() -> str | None:
    return _request_id.get()


def set_task_id(value: str | None) -> None:
    _task_id.set(value)


def get_task_id() -> str | None:
    return _task_id.get()


def reset_context() -> None:
    """Clear context vars -- called at the end of every request."""
    _request_id.set(None)
    _task_id.set(None)
