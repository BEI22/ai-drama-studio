"""Image provider selection (PRD section 16: business code must not know vendors).

``IMAGE_PROVIDER`` decides which implementation the image service receives:

    mock    (default) offline deterministic PNGs -- no key, no network, no cost
    openai  any OpenAI-compatible POST /images/generations endpoint

The returned object is always typed as :class:`ImageProvider`, so swapping
vendors never touches the image service or the API layer.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.exceptions import UnsupportedError
from app.providers.base import ImageProvider
from app.providers.image.mock import MockImageProvider
from app.providers.image.openai_compatible import OpenAICompatibleImageProvider

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = ("mock", "openai", "openai-compatible")


def build_image_provider(config: Settings) -> ImageProvider:
    """Construct the configured provider (no caching -- see ``get_image_provider``)."""
    name = (config.image_provider or "mock").strip().lower()

    if name == "mock":
        logger.info("using MockImageProvider (no real image will be generated)")
        return MockImageProvider(
            fail_times=config.mock_image_fail_times,
            max_pixels=config.mock_image_max_pixels,
        )

    if name in {"openai", "openai-compatible"}:
        if not config.image_api_key:
            # Fail loudly at selection time rather than on the first request.
            raise UnsupportedError(
                "IMAGE_PROVIDER 设为 openai 但未配置 IMAGE_API_KEY，请设置环境变量"
            )
        return OpenAICompatibleImageProvider(
            api_key=config.image_api_key,
            base_url=config.image_base_url,
            model=config.image_model,
            timeout_seconds=config.image_timeout_seconds,
        )

    raise UnsupportedError(
        f"未知的 IMAGE_PROVIDER: {name!r}（支持：{', '.join(SUPPORTED_PROVIDERS)}）"
    )


@lru_cache
def get_image_provider() -> ImageProvider:
    """Process-wide singleton used by the image service and the worker."""
    return build_image_provider(get_settings())


def reset_image_provider() -> None:
    """Drop the cached singleton -- tests use this after changing settings."""
    get_image_provider.cache_clear()


__all__ = [
    "SUPPORTED_PROVIDERS",
    "build_image_provider",
    "get_image_provider",
    "reset_image_provider",
]
