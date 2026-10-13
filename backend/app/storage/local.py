"""Local-filesystem storage backend (PRD sections 25, 39).

The V1 default: bytes land under ``STORAGE_LOCAL_DIR`` on a Docker volume and are
served back through the signed ``/files/{key}`` route. PRD section 39 prefers
S3/OSS, and this class exists so that preference is an implementation swap rather
than a rewrite -- the key layout is already object-store shaped
(``project/<id>/shots/<id>.png``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.storage.base import StorageBackend, StorageError, normalise_key

logger = logging.getLogger(__name__)


class LocalStorage(StorageBackend):
    name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- internals --------------------------------------------------------
    def _path_for(self, key: str) -> Path:
        """Resolve ``key`` under the root, refusing anything that escapes it.

        ``normalise_key`` rejects ``..`` components, but resolving and comparing
        again here means a symlink or a platform quirk still cannot read outside
        the root -- an untrusted path should never be trusted once.
        """
        safe = normalise_key(key)
        target = (self.root / safe).resolve()
        if target != self.root and self.root not in target.parents:
            raise StorageError(f"存储路径越界: {key!r}")
        return target

    # -- interface --------------------------------------------------------
    def save(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        target = self._path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then rename: a crash mid-write must not leave a
        # truncated image behind that later looks like a valid asset.
        temp = target.with_suffix(target.suffix + ".part")
        temp.write_bytes(data)
        temp.replace(target)
        logger.info(
            "stored object",
            extra={"storage_key": key, "bytes": len(data), "content_type": content_type},
        )
        return normalise_key(key)

    def read(self, key: str) -> bytes:
        target = self._path_for(key)
        if not target.is_file():
            raise StorageError(f"对象不存在: {key!r}")
        return target.read_bytes()

    def exists(self, key: str) -> bool:
        try:
            return self._path_for(key).is_file()
        except StorageError:
            return False

    def delete(self, key: str) -> None:
        target = self._path_for(key)
        target.unlink(missing_ok=True)
