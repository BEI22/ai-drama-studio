"""Storage abstraction (PRD sections 25, 39).

PRD section 25 fixes what the *database* keeps -- ``storage_key`` / ``url`` /
``metadata`` -- and forbids putting media in PostgreSQL. Section 39 names S3/OSS
as the eventual backend.

Business code therefore never touches the filesystem: it asks a
:class:`StorageBackend` to save bytes and gets back a key. Swapping in an object
store later is a new implementation of this interface, not a rewrite of the
image service.

Provider-owned detail lives in ``metadata_json`` (PRD section 25), not in columns.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

# Anything outside this set is rejected. Keys arrive from provider output and
# from URL paths, so a key is untrusted input: without this a key containing
# ".." would let a request read outside the storage root.
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class StorageError(RuntimeError):
    """Raised when a key is unsafe or the backend cannot satisfy a request."""


def normalise_key(key: str) -> str:
    """Validate a storage key, rejecting traversal and absolute paths.

    Absolute paths are *rejected* rather than silently stripped: rewriting
    ``/abs/path.png`` into ``abs/path.png`` would resolve safely, but quietly
    changing what the caller asked for is how a key ends up not meaning what its
    producer thinks it means. A key is either well-formed or it is an error.
    """
    candidate = (key or "").strip()
    if not candidate or candidate.startswith("/") or not _SAFE_KEY.match(candidate):
        raise StorageError(f"非法存储路径: {key!r}")
    # ``re`` alone would accept "a/../../b" -- the components have to be checked.
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageError(f"非法存储路径: {key!r}")
    return candidate


class StorageBackend(ABC):
    """Minimal surface the image pipeline needs."""

    name: str = "abstract"

    @abstractmethod
    def save(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        """Persist ``data`` under ``key`` and return the normalised key."""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Return the bytes stored under ``key`` (raises :class:`StorageError`)."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...
