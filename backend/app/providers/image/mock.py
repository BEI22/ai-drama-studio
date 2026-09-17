"""Deterministic offline image provider.

This is the default (``IMAGE_PROVIDER=mock``) and it produces **real PNG bytes**,
not a placeholder stub: the whole image pipeline -- prompt build, provider call,
storage write, asset row, signed URL, browser render -- is exercised and verified
with no key, no network and no cost.

What it draws is derived entirely from ``sha256(prompt)``, which buys three
things:

* **Deterministic** -- the same prompt always yields byte-identical output, so
  "must be idempotent" (PRD section 21) is testable rather than aspirational.
* **Distinguishable** -- different prompts yield visibly different colours and
  layouts, so a human (or a screenshot) can tell 47 distinct shots from 47 copies
  of one image.
* **Self-describing** -- the bottom strip encodes the first 32 bits of that hash
  as black/white bars. A verifier can re-derive the bits from the shot's own
  prompt and compare them against the pixels actually stored, which proves the
  file was generated *for that shot* instead of being a static fixture.

It is explicitly not a model: the banding is decoration, not composition.
"""

from __future__ import annotations

import hashlib
import struct
import time

from app.core.exceptions import ProviderError
from app.providers.base import ImageProvider, ImageRequest, ImageResult
from app.utils.png import encode_png

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 360

# The barcode strip: 32 bars, each a single bit of the prompt hash.
_BAR_COUNT = 32
_BAR_WIDTH = 8
_BAR_HEIGHT = 20
_BAR_LEFT = 16
_BAR_BOTTOM = 16

_FRAME = 4  # dark border thickness


def _digest(prompt: str) -> bytes:
    return hashlib.sha256(prompt.encode("utf-8")).digest()


def prompt_bits(prompt: str) -> list[int]:
    """The 32 bits the barcode encodes -- shared by provider and verifier."""
    return [(byte >> (7 - i)) & 1 for byte in _digest(prompt)[:4] for i in range(8)]


def _palette(prompt: str) -> tuple[tuple[int, int, int], ...]:
    digest = _digest(prompt)

    # Keep each channel in a mid range: neon-on-black looks like an error screen.
    def channel(offset: int) -> int:
        return 48 + digest[offset] % 160

    return (
        (channel(4), channel(5), channel(6)),  # sky
        (channel(7), channel(8), channel(9)),  # ground
        (channel(10), channel(11), channel(12)),  # accent / subject
    )


def render_mock_image(prompt: str, width: int, height: int) -> bytes:
    """Build the PNG for ``prompt``."""
    sky, ground, accent = _palette(prompt)
    digest = _digest(prompt)
    horizon = int(height * (0.45 + (digest[13] % 25) / 100.0))
    subject_w = max(24, width // 5)
    subject_h = max(24, int(height * 0.34))
    subject_x = _BAR_LEFT + (digest[14] % max(1, width - subject_w - 2 * _BAR_LEFT))
    subject_y = max(_FRAME + 4, horizon - subject_h)

    bars = prompt_bits(prompt)
    bar_top = height - _BAR_BOTTOM - _BAR_HEIGHT

    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            if x < _FRAME or y < _FRAME or x >= width - _FRAME or y >= height - _FRAME:
                pixel = (18, 18, 22)  # frame
            elif bars and bar_top <= y < bar_top + _BAR_HEIGHT:
                index = (x - _BAR_LEFT) // _BAR_WIDTH
                if 0 <= index < _BAR_COUNT and x >= _BAR_LEFT:
                    pixel = (245, 245, 245) if bars[index] else (12, 12, 12)
                else:
                    pixel = (30, 30, 34)
            elif subject_x <= x < subject_x + subject_w and subject_y <= y < subject_y + subject_h:
                # A soft vertical gradient on the "subject" block.
                t = (y - subject_y) / max(1, subject_h)
                pixel = (
                    int(accent[0] * (0.7 + 0.3 * t)),
                    int(accent[1] * (0.7 + 0.3 * t)),
                    int(accent[2] * (0.7 + 0.3 * t)),
                )
            elif y < horizon:
                # Sky: gradient top -> horizon.
                t = y / max(1, horizon)
                pixel = (
                    int(sky[0] * (0.55 + 0.45 * t)),
                    int(sky[1] * (0.55 + 0.45 * t)),
                    int(sky[2] * (0.55 + 0.45 * t)),
                )
            else:
                # Ground: bands, cheaper to compress and easy to eyeball.
                band = (y - horizon) // max(1, height // 24)
                shade = 0.45 + 0.08 * (band % 5)
                pixel = (
                    int(ground[0] * shade),
                    int(ground[1] * shade),
                    int(ground[2] * shade),
                )
            row.append(pixel)
        rows.append(row)

    return encode_png(width, height, rows)


class MockImageProvider(ImageProvider):
    """Offline provider. Returns bytes; the service owns storage (see ImageResult).

    ``fail_times`` raises for the first N calls -- the retry/FAILED path in PRD
    section 21 is otherwise impossible to reach deliberately offline, which means
    it is otherwise impossible to *test*.

    ``max_pixels`` scales the requested size down to a pixel budget. Pure-Python
    rendering of a 1024x1024 frame takes seconds; the numbers reported in
    ``ImageResult`` and in ``metadata`` are always the size actually produced,
    plus the size that was asked for, so nothing downstream is misled.
    """

    name: str = "mock"
    model: str = "mock-diffusion-v1"

    def __init__(
        self,
        *,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fail_times: int = 0,
        max_pixels: int = 240_000,
    ) -> None:
        super().__init__()
        self._width = width
        self._height = height
        self._fail_times = max(0, fail_times)
        self._max_pixels = max(1_000, max_pixels)
        self._calls = 0

    async def health(self) -> bool:
        return True

    @staticmethod
    def _fit(width: int, height: int, max_pixels: int) -> tuple[int, int]:
        """Shrink ``width``x``height`` to fit ``max_pixels``, preserving aspect."""
        if width * height <= max_pixels:
            return width, height
        scale = (max_pixels / (width * height)) ** 0.5
        return max(16, int(width * scale)), max(16, int(height * scale))

    async def generate(self, request: ImageRequest) -> ImageResult:
        self._calls += 1
        if self._calls <= self._fail_times:
            # Same exception type the real provider raises, so the retry path in
            # the image service is genuinely exercised (not a special case).
            raise ProviderError(
                f"mock image provider 故意失败（第 {self._calls}/{self._fail_times} 次）"
            )

        started = time.perf_counter()
        requested_w = request.width or self._width
        requested_h = request.height or self._height
        width, height = self._fit(requested_w, requested_h, self._max_pixels)
        data = render_mock_image(request.prompt, width, height)
        elapsed_ms = (time.perf_counter() - started) * 1000

        return ImageResult(
            data=data,
            width=width,
            height=height,
            estimated_cost=0.0,
            metadata={
                "provider": self.name,
                "model": self.model,
                "mock": True,
                "width": width,
                "height": height,
                "requested_size": f"{requested_w}x{requested_h}",
                "bytes": len(data),
                "prompt_sha256": _digest(request.prompt).hex(),
                "latency_ms": round(elapsed_ms, 2),
                "prompt_version": request.prompt_version,
                "seed": request.seed,
                "negative_prompt": request.negative_prompt,
                "reference_image_url": request.reference_image_url,
                # Keeps ``struct`` honest: the digest is unpacked from bytes, so
                # this cannot drift from prompt_bits().
                "barcode_prefix": struct.unpack(">I", _digest(request.prompt)[:4])[0],
            },
        )
