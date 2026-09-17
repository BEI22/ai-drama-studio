"""Vendor-neutral provider interfaces (PRD section 16).

Each interface takes a request object and returns a result object so that
swapping vendors never changes business-layer code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class Provider(BaseModel, ABC):
    """Common configuration surface for every provider."""

    model_config = {"arbitrary_types_allowed": True, "protected_namespaces": ()}

    name: str = "abstract"
    model: str | None = None
    timeout_seconds: float = 120.0

    @abstractmethod
    async def health(self) -> bool:
        """Cheap reachability check used by task workers before dispatching."""


# --------------------------------------------------------------------------- LLM
class LLMRequest(BaseModel):
    prompt: str
    system: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    json_schema: dict[str, Any] | None = None
    prompt_version: str | None = None


class LLMResult(BaseModel):
    text: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0


class LLMProvider(Provider, ABC):
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResult: ...


# ------------------------------------------------------------------------- Image
class ImageRequest(BaseModel):
    prompt: str
    negative_prompt: str | None = None
    width: int = 1024
    height: int = 1024
    reference_image_url: str | None = None
    seed: int | None = None
    prompt_version: str | None = None


class ImageResult(BaseModel):
    """Outcome of one image generation.

    ``data`` carries the raw bytes when the provider returned them (base64 or an
    inline blob); ``url`` when the vendor hosts the file itself. Providers do NOT
    write to storage: persisting the asset is the service's job, which keeps
    vendors swappable and lets a provider be tested without a filesystem.
    """

    data: bytes | None = None
    url: str | None = None
    storage_key: str | None = None
    width: int | None = None
    height: int | None = None
    estimated_cost: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageProvider(Provider, ABC):
    @abstractmethod
    async def generate(self, request: ImageRequest) -> ImageResult: ...


# ------------------------------------------------------------------------- Video
class VideoRequest(BaseModel):
    prompt: str
    image_url: str | None = None
    duration_seconds: float = 5.0
    fps: int = 24
    prompt_version: str | None = None


class VideoResult(BaseModel):
    url: str | None = None
    storage_key: str | None = None
    duration_seconds: float | None = None
    estimated_cost: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VideoProvider(Provider, ABC):
    @abstractmethod
    async def generate(self, request: VideoRequest) -> VideoResult: ...


# --------------------------------------------------------------------------- TTS
class TTSRequest(BaseModel):
    text: str
    voice_id: str
    speed: float = 1.0
    emotion: str | None = None
    prompt_version: str | None = None


class TTSResult(BaseModel):
    url: str | None = None
    storage_key: str | None = None
    duration_seconds: float | None = None
    estimated_cost: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TTSProvider(Provider, ABC):
    @abstractmethod
    async def generate(self, request: TTSRequest) -> TTSResult: ...
