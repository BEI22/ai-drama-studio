"""Storage backend selection (PRD sections 25, 39).

``STORAGE_BACKEND`` picks the implementation, mirroring the provider factories:
business code depends only on :class:`StorageBackend`.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.exceptions import UnsupportedError
from app.storage.base import StorageBackend, StorageError, normalise_key
from app.storage.local import LocalStorage

SUPPORTED_BACKENDS = ("local",)


def build_storage(config: Settings) -> StorageBackend:
    name = (config.storage_backend or "local").strip().lower()
    if name == "local":
        return LocalStorage(config.storage_local_dir)
    raise UnsupportedError(
        f"未知的 STORAGE_BACKEND: {name!r}（支持：{', '.join(SUPPORTED_BACKENDS)}）"
    )


@lru_cache
def get_storage() -> StorageBackend:
    """Process-wide singleton -- the backend holds no per-request state."""
    return build_storage(get_settings())


def reset_storage() -> None:
    """Drop the cached backend -- tests use this after changing settings."""
    get_storage.cache_clear()


__all__ = [
    "SUPPORTED_BACKENDS",
    "StorageBackend",
    "StorageError",
    "build_storage",
    "get_storage",
    "normalise_key",
    "reset_storage",
]
