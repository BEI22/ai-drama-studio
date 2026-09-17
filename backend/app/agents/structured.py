"""Structured LLM output: JSON extraction, schema validation, retry.

PRD section 6: "JSON 必须结构化 / AI 输出不能直接作为数据库自由文本使用 / 后端必须进行
JSON Schema 校验 / 校验失败需要自动修复或重试".

This module is the single place that turns an LLM's free text into a validated
Pydantic object. Every node goes through it, so no agent can accidentally persist
unvalidated model output.

Retry strategy:

1. First attempt sends the node's prompt unchanged.
2. On parse/validation failure, the next attempt **appends the concrete error**
   plus the required JSON schema, which is far more effective than blindly
   re-sending the same prompt.
3. After ``max_retries`` attempts the run fails with ``GENERATION_FAILED`` and
   the last error is preserved for the UI.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.exceptions import GenerationFailedError, ProviderError
from app.providers.base import LLMProvider, LLMRequest, LLMResult

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

# Appended to the prompt on a retry so the model sees exactly what was wrong.
_REPAIR_TEMPLATE = """

---
上一次输出无法通过校验，请修正后重新输出。

错误信息：
{error}

必须严格符合以下 JSON Schema（只输出 JSON 对象，不要 Markdown 代码块，不要任何解释文字）：
{schema}
"""


def _scan_first_json(text: str) -> object:
    """Parse the first *complete* JSON value in ``text``, ignoring what follows.

    This exists because the obvious heuristic -- take everything from the first
    ``{`` to the last ``}`` -- is wrong for a real failure mode: when a model emits
    two objects back to back (``{...}\\n{...}``), that span still contains two
    values and ``json.loads`` rejects it with "Extra data". Seen in production on
    the storyboard node: a ~12 KB object followed by a second one, which failed all
    three attempts and burned 160s before erroring out.

    ``raw_decode`` parses one value and reports where it ended, so trailing junk is
    irrelevant. Scanning forward (rather than taking a fixed position) also covers
    prose that contains an early unparseable ``{`` before the real payload.
    """
    decoder = json.JSONDecoder()
    cursor = 0
    length = len(text)

    while cursor < length:
        starts = [pos for pos in (text.find("{", cursor), text.find("[", cursor)) if pos != -1]
        if not starts:
            break
        start = min(starts)
        try:
            value, _end = decoder.raw_decode(text, start)
            return value
        except json.JSONDecodeError:
            # Not a JSON value here (prose brace, or a truncated object): advance
            # one character and look again.
            cursor = start + 1

    raise ValueError("输出中找不到完整的 JSON 值")


def extract_json(text: str) -> object:
    """Pull a JSON value out of an LLM response.

    Handles the shapes models actually produce: a bare object, an object wrapped in
    a ```json fence, an object buried in prose, and -- the case that used to fail --
    several JSON values concatenated, where the first complete one wins.
    """
    if not text or not text.strip():
        raise ValueError("LLM 返回内容为空")

    candidates: list[str] = []

    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())

    stripped = text.strip()
    candidates.append(stripped)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

    # Nothing parsed as a whole document. Fall back to scanning for the first
    # complete value -- this is what rescues concatenated or commentary-wrapped
    # output.
    for candidate in candidates:
        try:
            return _scan_first_json(candidate)
        except ValueError as exc:
            last_error = last_error or exc
            continue

    raise ValueError(f"无法从 LLM 输出中解析 JSON：{last_error}")


async def generate_structured(
    provider: LLMProvider,
    request: LLMRequest,
    schema: type[ModelT],
    *,
    max_retries: int | None = None,
    post_validate: Callable[[ModelT], None] | None = None,
) -> tuple[ModelT, LLMResult]:
    """Call ``provider`` until its output validates against ``schema``.

    Returns the validated model plus the raw :class:`LLMResult` of the successful
    call (so callers can record tokens/model/prompt version).

    ``post_validate`` runs after schema validation and may raise ``ValueError`` to
    force a retry with the reason fed back to the model. It exists because some
    requirements cannot be expressed in the schema alone -- PRD section 10's
    "不允许 AI 随意创建数据库中不存在的人物 ID" needs to compare the output against
    the project's actual roster, which the schema has no access to. Keeping it
    here means there is still exactly one retry mechanism rather than a second
    hand-rolled loop in the node.
    """
    attempts = max(1, max_retries if max_retries is not None else settings.llm_max_retries)

    # Always tell the provider which schema we expect; the mock routes on it and
    # real endpoints can use it for response_format / json_schema.
    json_schema = schema.model_json_schema()
    base_request = request.model_copy(update={"json_schema": json_schema})

    prompt = request.prompt
    last_error_text = ""

    for attempt in range(1, attempts + 1):
        current = base_request.model_copy(update={"prompt": prompt})

        try:
            result = await provider.generate(current)
        except ProviderError as exc:
            # Provider/transport failures are retried the same way as schema
            # failures -- both are typically transient.
            last_error_text = str(exc)
            logger.warning("LLM 调用失败（第 %d/%d 次）：%s", attempt, attempts, exc)
            prompt = request.prompt + _REPAIR_TEMPLATE.format(
                error=last_error_text,
                schema=json.dumps(json_schema, ensure_ascii=False)[:2000],
            )
            continue

        try:
            payload = extract_json(result.text)
            validated = schema.model_validate(payload)
            if post_validate is not None:
                post_validate(validated)
        except (ValueError, ValidationError) as exc:
            last_error_text = _format_error(exc)
            logger.warning(
                "LLM 输出校验失败（第 %d/%d 次）：%s", attempt, attempts, last_error_text
            )
            prompt = request.prompt + _REPAIR_TEMPLATE.format(
                error=last_error_text,
                schema=json.dumps(json_schema, ensure_ascii=False)[:2000],
            )
            continue

        if attempt > 1:
            logger.info("LLM 输出在第 %d 次尝试后通过校验", attempt)
        return validated, result

    raise GenerationFailedError(
        f"AI 输出在 {attempts} 次尝试后仍无法通过 Schema 校验：{last_error_text[:400]}",
        details={"attempts": attempts, "last_error": last_error_text[:1000]},
    )


def _format_error(exc: Exception) -> str:
    """Compact, model-readable description of why validation failed."""
    if isinstance(exc, ValidationError):
        parts = []
        for error in exc.errors()[:15]:
            location = ".".join(str(item) for item in error.get("loc", ())) or "<root>"
            parts.append(f"- {location}: {error.get('msg', '')}")
        return "\n".join(parts) or str(exc)
    return str(exc)


__all__ = ["extract_json", "generate_structured"]
