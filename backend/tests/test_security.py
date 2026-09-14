"""Password hashing and JWT helpers (PRD section 27)."""

from __future__ import annotations

import pytest

from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    password_hash = hash_password("correct horse battery staple")
    assert password_hash != "correct horse battery staple"
    assert password_hash.startswith("$2")
    assert verify_password("correct horse battery staple", password_hash)
    assert not verify_password("wrong password", password_hash)


def test_long_passwords_are_not_truncated() -> None:
    """bcrypt caps at 72 bytes; we pre-hash so long passphrases stay distinct."""
    base = "x" * 72
    password_hash = hash_password(base + "AAAA")
    assert not verify_password(base + "BBBB", password_hash)
    assert verify_password(base + "AAAA", password_hash)


def test_hash_is_salted() -> None:
    assert hash_password("same") != hash_password("same")


def test_verify_password_tolerates_garbage_hash() -> None:
    assert not verify_password("pw", "not-a-bcrypt-hash")


def test_access_token_round_trip() -> None:
    token = create_access_token("user-123", extra_claims={"email": "a@example.com"})
    claims = decode_access_token(token)
    assert claims["sub"] == "user-123"
    assert claims["email"] == "a@example.com"
    assert claims["exp"] > claims["iat"]


def test_expired_token_is_rejected() -> None:
    token = create_access_token("user-123", expires_minutes=-1)
    with pytest.raises(UnauthorizedError):
        decode_access_token(token)


def test_tampered_token_is_rejected() -> None:
    token = create_access_token("user-123")
    with pytest.raises(UnauthorizedError):
        decode_access_token(token + "tampered")
