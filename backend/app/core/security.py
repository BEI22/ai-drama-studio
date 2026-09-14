"""Password hashing and JWT helpers (PRD section 27).

Passwords are pre-hashed with SHA-256 before bcrypt so that bcrypt's 72-byte
input limit can never silently truncate a long passphrase.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError


def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    """Return a bcrypt hash for ``password``."""
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish verification of ``password`` against ``password_hash``."""
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    *,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Issue a signed JWT for ``subject`` (a user id)."""
    expires_delta = timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode a JWT, raising :class:`UnauthorizedError` when invalid/expired."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # pragma: no cover - exercised via API tests
        raise UnauthorizedError("Invalid or expired token") from exc
