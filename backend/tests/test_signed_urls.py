"""Signed-URL freshness tests (PRD section 27).

The bug these lock down: the reference-image columns persist a *signed* URL, and a
signature expires. Storing it verbatim meant a character reference image worked for
one hour and was then a dead link permanently -- the picture was on disk the whole
time, only the URL had rotted.
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.signing import (
    resign_storage_url,
    sign_storage_url,
    storage_key_from_url,
    verify_storage_signature,
)

REGISTER = "/api/v1/auth/register"
PASSWORD = "signtime2026"

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "班主任周老师走进教室，宣布了考研的报名时间。"
)


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _data(response) -> dict:
    assert response.status_code < 300, response.text
    return response.json()["data"]


class TestStorageKeyRecovery:
    def test_key_is_recovered_from_a_signed_url(self):
        key = "project/abc/shots/def.png"
        url = sign_storage_url(key, ttl_seconds=60)
        assert storage_key_from_url(url) == key

    def test_a_foreign_url_yields_nothing(self):
        """An external image must be left alone, not mangled into a local path."""
        assert storage_key_from_url("https://cdn.example.com/pic.png") is None
        assert storage_key_from_url("") is None
        assert storage_key_from_url("not a url") is None


class TestResigning:
    def test_resigning_extends_the_expiry_and_still_verifies(self):
        key = "project/a/shots/b.png"
        stale = sign_storage_url(key, ttl_seconds=-100)  # already expired
        parsed = dict(part.split("=", 1) for part in stale.split("?", 1)[1].split("&"))
        assert not verify_storage_signature(key, parsed["expires"], parsed["sig"])

        fresh = resign_storage_url(stale, ttl_seconds=3600)
        assert fresh is not None
        fresh_query = dict(part.split("=", 1) for part in fresh.split("?", 1)[1].split("&"))
        assert int(fresh_query["expires"]) > int(time.time())
        assert verify_storage_signature(key, fresh_query["expires"], fresh_query["sig"])

    def test_the_key_survives_resigning(self):
        key = "project/a/characters/c.png"
        first = sign_storage_url(key, ttl_seconds=10)
        second = resign_storage_url(first, ttl_seconds=3600)
        assert storage_key_from_url(second) == key

    def test_none_and_foreign_values_pass_through_unchanged(self):
        assert resign_storage_url(None) is None
        assert (
            resign_storage_url("https://cdn.example.com/x.png") == "https://cdn.example.com/x.png"
        )


class TestReferenceUrlStaysFresh:
    """End-to-end: the API must never hand back an expired reference URL."""

    @pytest.fixture
    def project_and_bible(self, client: TestClient):
        email = f"sign-{uuid.uuid4().hex[:8]}@example.com"
        token = _data(client.post(REGISTER, json={"email": email, "password": PASSWORD}))[
            "access_token"
        ]
        project_id = _data(
            client.post(
                "/api/v1/projects",
                json={
                    "name": "签名新鲜度",
                    "genre": "都市",
                    "style": "国漫",
                    "story_source": "SYNOPSIS",
                    "story_text": STORY,
                },
                headers=_headers(token),
            )
        )["id"]
        _data(client.post(f"/api/v1/projects/{project_id}/analyze", headers=_headers(token)))
        return token, project_id

    def test_a_stale_stored_url_is_refreshed_on_read(self, client: TestClient, project_and_bible):
        token, project_id = project_and_bible
        bible = _data(client.get(f"/api/v1/projects/{project_id}/bible", headers=_headers(token)))
        character_id = bible["characters"][0]["id"]

        _data(
            client.post(
                f"/api/v1/characters/{character_id}/reference/generate",
                headers=_headers(token),
                params={"force": "true"},
            )
        )

        # Simulate the hour passing: overwrite the stored URL with an expired one
        # for the same file, exactly as the row would look after the TTL ran out.
        from app.core.database import SessionLocal
        from app.models.character import Character

        db = SessionLocal()
        try:
            character = db.get(Character, uuid.UUID(character_id))
            key = storage_key_from_url(character.reference_image_url)
            assert key is not None
            character.reference_image_url = sign_storage_url(key, ttl_seconds=-60)
            db.commit()
        finally:
            db.close()

        # The read must return a usable URL, not the rotted one.
        refreshed = _data(
            client.get(f"/api/v1/projects/{project_id}/bible", headers=_headers(token))
        )
        url = {c["id"]: c for c in refreshed["characters"]}[character_id]["reference_image_url"]
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        assert int(query["expires"]) > int(time.time()), "参考图 URL 未被重新签名"

        path = url.split("http://testserver", 1)[1]
        response = client.get(path)
        assert response.status_code == 200, "重新签名后的 URL 应当可以下载"
        assert response.content.startswith(b"\x89PNG")
