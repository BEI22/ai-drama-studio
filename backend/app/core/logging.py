"""Structured logging.

Log records carry ``request_id`` (and ``task_id`` once async tasks land in a
later phase). A redaction filter guarantees API keys, tokens and passwords
never reach the log stream (PRD section 28).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.core.context import get_request_id, get_task_id

# Attribute names that must never be logged verbatim.
SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "new_password",
    "secret",
    "secret_key",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "authorization",
    "token",
    "bearer",
}

# Free-text patterns: ``sk-...``-style keys, bearer headers, password=...
_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***REDACTED***"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{8,}"), r"\1 ***REDACTED***"),
    (re.compile(r"(?i)\b(password|api_key|token|secret)\b\s*[=:]\s*\S+"), r"\1=***REDACTED***"),
)

_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
}


def redact(value: str) -> str:
    """Scrub secret-looking substrings from a log message."""
    for pattern, replacement in _REDACTION_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


class RedactionFilter(logging.Filter):
    """Remove sensitive values from records before they are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: ("***REDACTED***" if key.lower() in SENSITIVE_KEYS else value)
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    redact(arg) if isinstance(arg, str) else arg for arg in record.args
                )
        for key, value in list(record.__dict__.items()):
            if key.lower() in SENSITIVE_KEYS:
                record.__dict__[key] = "***REDACTED***"
            elif isinstance(value, str) and key not in _RESERVED:
                record.__dict__[key] = redact(value)
        return True


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line -- ready for log shippers."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            payload["request_id"] = request_id
        task_id = getattr(record, "task_id", None) or get_task_id()
        if task_id:
            payload["task_id"] = task_id

        for key, value in record.__dict__.items():
            if key in _RESERVED or key in payload or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class PlainFormatter(logging.Formatter):
    """Human readable single-line format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", None) or get_request_id() or "-"
        base = (
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.levelname:<8} [{request_id}] {record.name}: {record.getMessage()}"
        )
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def configure_logging(level: str = "INFO", json_output: bool = True) -> None:
    """Install a single stdout handler with redaction enabled."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn installs its own handlers; route them through ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    # SQLAlchemy is chatty at INFO; keep it at WARNING unless explicitly asked.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
