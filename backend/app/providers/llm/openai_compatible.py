"""OpenAI-compatible chat-completions provider (PRD section 16, 37 item 9).

Works against any ``/chat/completions`` endpoint -- OpenAI, DeepSeek, Moonshot,
Qwen/DashScope compatible mode, vLLM, Ollama, ... -- configured purely by
environment variables:

    LLM_PROVIDER=openai
    LLM_BASE_URL=https://api.deepseek.com/v1
    LLM_API_KEY=sk-...
    LLM_MODEL=deepseek-chat

No vendor SDK is imported; this is plain HTTP so the dependency surface stays
small and the abstraction is real (business code never sees this class).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.exceptions import ProviderError
from app.providers.base import LLMProvider, LLMRequest, LLMResult

logger = logging.getLogger(__name__)


def is_healthy_status(status_code: int) -> bool:
    """Map an HTTP status onto "is this provider usable?".

    The naive ``status < 500`` is wrong: it counts a 401 as healthy, so ops would
    see the provider as green while every real call fails on a bad key. Auth
    failures are the single most likely misconfiguration, so they must read as
    unhealthy.

    ``404``/``405`` are treated as healthy on purpose -- not every compatible
    endpoint implements ``GET /models``, and "route not found" still proves the
    host is reachable. Only genuine auth or server faults count as down.
    """
    if 200 <= status_code < 300:
        return True
    if status_code in (401, 403):
        return False
    if status_code in (404, 405, 501):
        return True
    return False


class OpenAICompatibleLLMProvider(LLMProvider):
    """Thin adapter over ``POST {base_url}/chat/completions``."""

    name: str = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 120.0,
    ) -> None:
        super().__init__(name="openai-compatible", model=model, timeout_seconds=timeout_seconds)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def health(self) -> bool:
        """A cheap check: is the endpoint reachable *and* is the key accepted?

        Only a reachable, correctly-authenticated endpoint counts as healthy --
        see :func:`is_healthy_status`.
        """
        if not self._api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self._base_url}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            return is_healthy_status(response.status_code)
        except httpx.HTTPError:
            return False

    async def generate(self, request: LLMRequest) -> LLMResult:
        if not self._api_key:
            raise ProviderError("未配置 LLM_API_KEY")

        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.json_schema:
            # Widely supported; endpoints that ignore it still return JSON
            # because the prompt asks for it.
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"调用 LLM 失败：{exc}") from exc

        if response.status_code >= 400:
            # Never echo the request headers; the body may contain the key.
            detail = response.text[:500]
            raise ProviderError(f"LLM 返回 {response.status_code}: {detail}")

        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"LLM 响应结构异常：{str(body)[:300]}") from exc

        usage = body.get("usage") or {}
        return LLMResult(
            text=text or "",
            model=body.get("model") or self.model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )
