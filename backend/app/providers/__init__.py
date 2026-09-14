"""Provider abstractions (PRD section 16).

Business logic must never call a vendor SDK directly -- every AI capability is
reached through one of the four interfaces below.

Phase 1 deliberately ships **interfaces only**: no real provider is wired up,
and the default ``*_provider`` settings remain ``"mock"`` until Phase 3.
"""

from app.providers.base import (
    ImageProvider,
    ImageRequest,
    ImageResult,
    LLMProvider,
    LLMRequest,
    LLMResult,
    Provider,
    TTSProvider,
    TTSRequest,
    TTSResult,
    VideoProvider,
    VideoRequest,
    VideoResult,
)

__all__ = [
    "ImageProvider",
    "ImageRequest",
    "ImageResult",
    "LLMProvider",
    "LLMRequest",
    "LLMResult",
    "Provider",
    "TTSProvider",
    "TTSRequest",
    "TTSResult",
    "VideoProvider",
    "VideoRequest",
    "VideoResult",
]
