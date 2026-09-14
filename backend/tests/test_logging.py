"""Structured logging must never leak secrets (PRD section 28)."""

from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, RedactionFilter, redact


def test_redact_scrubs_api_keys_and_passwords() -> None:
    assert "sk-***REDACTED***" in redact("calling with sk-proj-ABCdef1234567890")
    assert "***REDACTED***" in redact("password=hunter2")
    assert "***REDACTED***" in redact("Authorization: Bearer abcdef1234567890")
    assert redact("plain message") == "plain message"


def test_redaction_filter_scrubs_extra_fields() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="user payload",
        args=(),
        exc_info=None,
    )
    record.api_key = "sk-live-1234567890abcdef"
    record.password = "hunter2"

    RedactionFilter().filter(record)

    assert record.api_key == "***REDACTED***"
    assert record.password == "***REDACTED***"


def test_json_formatter_includes_request_id() -> None:
    from app.core.context import reset_context, set_request_id

    reset_context()
    set_request_id("req_unit_test")
    try:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="story parsed",
            args=(),
            exc_info=None,
        )
        record.project_id = "p-1"
        payload = json.loads(JsonFormatter().format(record))
    finally:
        reset_context()

    assert payload["message"] == "story parsed"
    assert payload["request_id"] == "req_unit_test"
    assert payload["project_id"] == "p-1"
    assert payload["level"] == "INFO"
