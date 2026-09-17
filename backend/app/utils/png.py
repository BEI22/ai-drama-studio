"""Minimal PNG encoder (stdlib only).

Why not Pillow: the mock image provider is the one that has to run everywhere
(tests, CI, the container) with no key and no network, so it must not depend on
an *undeclared* transitive package. Pillow happens to be present in the dev
virtualenv but is in neither ``pyproject.toml`` nor, necessarily, the image. A
PNG writer for 8-bit truecolour is ~40 lines with ``zlib`` and ``struct``, and
that is a much smaller liability than a dependency the runtime may not have.

Only what the pipeline needs: no interlacing, no palette, filter type 0 (None)
on every scanline.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence

# PRD section 25 forbids storing media in PostgreSQL; these bytes go to storage.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

Color = tuple[int, int, int]


def _chunk(tag: bytes, data: bytes) -> bytes:
    """One PNG chunk: length, tag, payload, CRC32 over tag+payload."""
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rows: Sequence[Sequence[Color]]) -> bytes:
    """Encode ``rows`` (top-to-bottom, each ``width`` pixels of RGB) as a PNG.

    Raises ``ValueError`` on a shape mismatch -- a silently mis-sized image would
    otherwise only be discovered by the browser, as a broken picture.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"图像尺寸必须为正: {width}x{height}")
    if len(rows) != height:
        raise ValueError(f"行数 {len(rows)} 与高度 {height} 不符")

    raw = bytearray()
    for y, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(f"第 {y} 行有 {len(row)} 像素，期望 {width}")
        raw.append(0)  # filter type 0 = None
        for pixel in row:
            raw.extend(pixel)

    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,  # bit depth
        2,  # colour type 2 = truecolour RGB
        0,  # compression: deflate
        0,  # filter method
        0,  # interlace: none
    )
    return (
        PNG_MAGIC
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def decode_png_size(data: bytes) -> tuple[int, int]:
    """Read ``(width, height)`` out of a PNG's IHDR.

    Used by tests and the HTTP verification to prove a stored file really is a
    PNG of the requested size, rather than trusting the provider's own metadata.
    """
    if not data.startswith(PNG_MAGIC):
        raise ValueError("不是 PNG 文件")
    if len(data) < 24 or data[12:16] != b"IHDR":
        raise ValueError("PNG 缺少 IHDR")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def decode_png_pixels(data: bytes, *, max_rows: int | None = None) -> list[list[Color]]:
    """Decode a truecolour PNG back to pixels (test/verification helper).

    Deliberately narrow: single IDAT, filter 0 only -- exactly the subset
    :func:`encode_png` produces. It exists to let a test *read back* what was
    written instead of asserting on a byte prefix.
    """
    if not data.startswith(PNG_MAGIC):
        raise ValueError("不是 PNG 文件")

    pos = 8
    width = height = 0
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        tag = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # length + tag + payload + crc
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", payload[:10])
            if depth != 8 or colour != 2:
                raise ValueError("只支持 8bit truecolour PNG")
        elif tag == b"IDAT":
            idat.extend(payload)
        elif tag == b"IEND":
            break

    raw = zlib.decompress(bytes(idat))
    stride = width * 3
    rows: list[list[Color]] = []
    limit = height if max_rows is None else min(height, max_rows)
    for y in range(limit):
        start = y * (stride + 1)
        if raw[start] != 0:
            raise ValueError(f"第 {y} 行使用了不支持的 filter {raw[start]}")
        line = raw[start + 1 : start + 1 + stride]
        rows.append([(line[i], line[i + 1], line[i + 2]) for i in range(0, stride, 3)])
    return rows
