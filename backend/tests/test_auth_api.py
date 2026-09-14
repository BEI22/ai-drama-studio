"""Authentication API tests (PRD sections 27, 36 item 11)."""

from __future__ import annotations

from fastapi.testclient import TestClient

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"

VALID = {"email": "author@example.com", "password": "storytime2026"}


def register(client: TestClient, **overrides) -> dict:
    payload = {**VALID, **overrides}
    return client.post(REGISTER, json=payload)


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------- register
def test_register_returns_token_and_user(client: TestClient) -> None:
    response = register(client)
    assert response.status_code == 201

    body = response.json()
    assert body["success"] is True
    assert body["error"] is None

    data = body["data"]
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["user"]["email"] == VALID["email"]
    assert "password" not in data["user"]
    assert "password_hash" not in data["user"]


def test_register_never_leaks_password_hash(client: TestClient) -> None:
    response = register(client)
    assert "password_hash" not in response.text
    assert "$2" not in response.text


def test_register_normalises_email_case(client: TestClient) -> None:
    first = register(client, email="MixedCase@Example.COM")
    assert first.status_code == 201
    assert first.json()["data"]["user"]["email"] == "mixedcase@example.com"

    # Same address in a different case must collide, not create a second account.
    duplicate = register(client, email="mixedcase@example.com")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONFLICT"


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    assert register(client).status_code == 201
    response = register(client)

    assert response.status_code == 409
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "CONFLICT"
    assert body["data"] is None


def test_register_rejects_short_password(client: TestClient) -> None:
    response = register(client, password="abc123")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_rejects_letters_only_password(client: TestClient) -> None:
    response = register(client, password="onlylettershere")
    assert response.status_code == 422


def test_register_rejects_digits_only_password(client: TestClient) -> None:
    response = register(client, password="1234567890123")
    assert response.status_code == 422


def test_register_rejects_invalid_email(client: TestClient) -> None:
    response = register(client, email="not-an-email")
    assert response.status_code == 422


# ------------------------------------------------------------------------ login
def test_login_succeeds_with_correct_credentials(client: TestClient) -> None:
    register(client)
    response = client.post(LOGIN, json=VALID)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["access_token"]


def test_login_is_case_insensitive_on_email(client: TestClient) -> None:
    register(client)
    response = client.post(
        LOGIN, json={"email": "AUTHOR@example.com", "password": VALID["password"]}
    )
    assert response.status_code == 200


def test_login_rejects_wrong_password(client: TestClient) -> None:
    register(client)
    response = client.post(LOGIN, json={**VALID, "password": "wrongpass123"})

    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_login_rejects_unknown_email(client: TestClient) -> None:
    response = client.post(LOGIN, json=VALID)
    assert response.status_code == 401
    # Same message as a wrong password so registered emails are not enumerable.
    assert response.json()["error"]["message"] == "邮箱或密码不正确"


def test_unknown_email_and_wrong_password_are_indistinguishable(client: TestClient) -> None:
    register(client)
    wrong_password = client.post(LOGIN, json={**VALID, "password": "wrongpass123"})
    unknown_email = client.post(
        LOGIN, json={"email": "nobody@example.com", "password": "whatever123"}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"] == unknown_email.json()["error"]


# --------------------------------------------------------------------------- me
def test_me_returns_current_user(client: TestClient) -> None:
    token = register(client).json()["data"]["access_token"]
    response = client.get(ME, headers=auth_header(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["email"] == VALID["email"]
    assert data["id"]


def test_me_requires_token(client: TestClient) -> None:
    response = client.get(ME)
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"
    assert body["success"] is False


def test_me_rejects_malformed_token(client: TestClient) -> None:
    response = client.get(ME, headers=auth_header("not-a-jwt"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_me_rejects_token_signed_with_other_key(client: TestClient) -> None:
    from jose import jwt

    forged = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000"}, "attacker-key", algorithm="HS256"
    )
    response = client.get(ME, headers=auth_header(forged))
    assert response.status_code == 401


def test_me_rejects_expired_token(client: TestClient) -> None:
    from app.core.security import create_access_token

    expired = create_access_token("00000000-0000-0000-0000-000000000000", expires_minutes=-1)
    response = client.get(ME, headers=auth_header(expired))
    assert response.status_code == 401


def test_token_for_deleted_user_is_rejected(client: TestClient) -> None:
    """A valid signature is not enough -- the subject must still exist."""
    import uuid

    from app.core.security import create_access_token

    ghost = create_access_token(str(uuid.uuid4()))
    response = client.get(ME, headers=auth_header(ghost))
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "用户不存在或已注销"
