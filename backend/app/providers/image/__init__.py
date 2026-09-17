"""Image provider implementations (PRD section 16, Phase 5).

Two ship in Phase 5: a deterministic offline mock that returns real PNG bytes,
and an OpenAI-compatible HTTP adapter. Business code only ever sees the
``ImageProvider`` interface.
"""

from app.providers.image.factory import (
    SUPPORTED_PROVIDERS,
    build_image_provider,
    get_image_provider,
    reset_image_provider,
)
from app.providers.image.mock import MockImageProvider
from app.providers.image.openai_compatible import OpenAICompatibleImageProvider

__all__ = [
    "SUPPORTED_PROVIDERS",
    "MockImageProvider",
    "OpenAICompatibleImageProvider",
    "build_image_provider",
    "get_image_provider",
    "reset_image_provider",
]
