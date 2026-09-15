"""LLM provider selection (PRD section 16: business code must not know vendors).

``LLM_PROVIDER`` decides which implementation is handed to the agents::

    mock    (default) offline deterministic heuristics -- no key, no network
    openai  any OpenAI-compatible /chat/completions endpoint

The returned object is always typed as :class:`LLMProvider`, so swapping vendors
never touches the agents.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.exceptions import UnsupportedError
from app.providers.base import LLMProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("mock", "openai", "openai-compatible")


def build_llm_provider(config: Settings) -> LLMProvider:
    """Construct the configured provider (no caching -- see ``get_llm_provider``)."""
    name = (config.llm_provider or "mock").strip().lower()

    if name == "mock":
        provider = MockLLMProvider(
            fail_times=config.mock_llm_fail_times,
            latency_ms=config.mock_llm_latency_ms,
        )
        logger.info("using MockLLMProvider (no real AI call will be made)")
        return provider

    if name in {"openai", "openai-compatible"}:
        if not config.llm_api_key:
            # Fail loudly at selection time rather than on the first request.
            raise UnsupportedError("LLM_PROVIDER 设为 openai 但未配置 LLM_API_KEY，请设置环境变量")
        return OpenAICompatibleLLMProvider(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
            timeout_seconds=config.llm_timeout_seconds,
        )

    raise UnsupportedError(
        f"未知的 LLM_PROVIDER: {name!r}（支持：{', '.join(SUPPORTED_PROVIDERS)}）"
    )


@lru_cache
def get_llm_provider() -> LLMProvider:
    """Process-wide singleton used by the agents."""
    return build_llm_provider(get_settings())


def reset_llm_provider() -> None:
    """Drop the cached singleton -- tests use this after changing settings."""
    get_llm_provider.cache_clear()


__all__ = [
    "SUPPORTED_PROVIDERS",
    "build_llm_provider",
    "get_llm_provider",
    "reset_llm_provider",
]
