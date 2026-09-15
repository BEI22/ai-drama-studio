"""LLM provider implementations.

Phase 3 ships two: a deterministic offline mock, and an OpenAI-compatible HTTP
adapter. Business code only ever sees the ``LLMProvider`` interface.
"""

from app.providers.llm.factory import (
    SUPPORTED_PROVIDERS,
    build_llm_provider,
    get_llm_provider,
    reset_llm_provider,
)
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

__all__ = [
    "SUPPORTED_PROVIDERS",
    "MockLLMProvider",
    "OpenAICompatibleLLMProvider",
    "build_llm_provider",
    "get_llm_provider",
    "reset_llm_provider",
]
