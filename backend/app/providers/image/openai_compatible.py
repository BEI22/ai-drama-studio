"""OpenAI-compatible image provider (PRD section 16).

Works against any ``POST {base_url}/images/generations`` endpoint configured by
environment variables:

    IMAGE_PROVIDER=openai
    IMAGE_BASE_URL=https://api.openai.com/v1
    IMAGE_API_KEY=sk-...
    IMAGE_MODEL=gpt-image-1

Plain HTTP, no vendor SDK, and the same health semantics as the LLM adapter
(a 401 is *unhealthy* -- see ``is_healthy_status``).

On the Reference Image layer (PRD section 19): this adapter sends a **text-only**
generation call. Reference conditioning (``/images/edits``, or a vendor's own
image field) is not expressible in the portable ``/images/generations`` contract,
so rather than send a field that some endpoints reject and others silently
ignore, the reference is handled at the *prompt* level -- the Character/Scene
Bible description of the referenced image is merged into the prompt text by the
Prompt Builder -- and ``reference_image_url`` is still recorded on the request
and in the returned metadata so a vendor-specific adapter can use it later.
Pretending to send conditioning we cannot verify would be worse than saying so.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from typing import Any

import httpx

from app.core.exceptions import ProviderError
from app.providers.base import ImageProvider, ImageRequest, ImageResult
from app.providers.llm.openai_compatible import is_healthy_status

logger = logging.getLogger(__name__)


class OpenAICompatibleImageProvider(ImageProvider):
    """Thin adapter over ``POST {base_url}/images/generations``."""

    name: str = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 180.0,
    ) -> None:
        super().__init__(name="openai-compatible", model=model, timeout_seconds=timeout_seconds)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def health(self) -> bool:
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

    async def generate(self, request: ImageRequest) -> ImageResult:
        if not self._api_key:
            raise ProviderError("未配置 IMAGE_API_KEY")

        size = f"{request.width}x{request.height}"
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": request.prompt,
            "n": 1,
            "size": size,
            # Prefer inline bytes: a returned URL is usually short-lived, and the
            # asset has to be persisted under our own key anyway.
            "response_format": "b64_json",
        }
        if request.negative_prompt:
            # Not part of the portable contract; vendors that support it honour
            # it, others ignore unknown fields. Kept because dropping a caller's
            # explicit exclusion would change the picture.
            payload["negative_prompt"] = request.negative_prompt

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/images/generations",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise ProviderError(f"调用图像服务失败：{exc}") from exc

        if response.status_code >= 400:
            # Never echo request headers; the body may contain the key.
            raise ProviderError(f"图像服务返回 {response.status_code}: {response.text[:500]}")

        body = response.json()
        try:
            entry = body["data"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"图像响应结构异常：{str(body)[:300]}") from exc

        data: bytes | None = None
        url: str | None = entry.get("url")
        if entry.get("b64_json"):
            try:
                data = base64.b64decode(entry["b64_json"], validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ProviderError("图像响应中的 b64_json 无法解码") from exc
        elif url:
            # Endpoint ignored response_format and hosted the file instead of
            # inlining it, so fetch the bytes: the asset must outlive their URL.
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    fetched = await client.get(url)
                fetched.raise_for_status()
                data = fetched.content
            except httpx.HTTPError as exc:
                raise ProviderError(f"下载图像结果失败：{exc}") from exc
        else:
            raise ProviderError(f"图像响应既没有 b64_json 也没有 url：{str(entry)[:200]}")

        width, height = _parse_size(entry.get("size") or size)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ImageResult(
            data=data,
            url=url,
            width=width,
            height=height,
            metadata={
                "provider": self.name,
                "model": body.get("model") or self.model,
                "mock": False,
                "bytes": len(data) if data else 0,
                "requested_size": size,
                "latency_ms": round(elapsed_ms, 2),
                "prompt_version": request.prompt_version,
                "seed": request.seed,
                "reference_image_url": request.reference_image_url,
                "reference_conditioning": "prompt-level" if request.reference_image_url else None,
                "revised_prompt": entry.get("revised_prompt"),
            },
        )


def _parse_size(size: str) -> tuple[int | None, int | None]:
    """``"1024x1024"`` -> ``(1024, 1024)``; unknown shapes -> ``(None, None)``."""
    try:
        width_text, height_text = str(size).lower().split("x", 1)
        return int(width_text), int(height_text)
    except (ValueError, AttributeError):
        return None, None
