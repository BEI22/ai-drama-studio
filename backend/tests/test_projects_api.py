"""Project + Story API tests (PRD sections 22, 27, 36).

The headline requirement is isolation: one user must never reach another user's
project, through any verb.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

PROJECTS = "/api/v1/projects"
REGISTER = "/api/v1/auth/register"


def make_user(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(REGISTER, json={"email": email, "password": "storytime2026"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@pytest.fixture
def alice(client: TestClient) -> dict[str, str]:
    return make_user(client, "alice@example.com")


@pytest.fixture
def bob(client: TestClient) -> dict[str, str]:
    return make_user(client, "bob@example.com")


def create_project(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {"name": "重生大学时代", "genre": "都市", "style": "国漫", **overrides}
    response = client.post(PROJECTS, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["data"]


# -------------------------------------------------------------------- auth gate
@pytest.mark.parametrize(
    "method,kwargs",
    [("get", {}), ("post", {"json": {"name": "x"}})],
)
def test_project_endpoints_require_auth(client: TestClient, method: str, kwargs: dict) -> None:
    response = getattr(client, method)(PROJECTS, **kwargs)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_project_detail_requires_auth(client: TestClient) -> None:
    response = client.get(f"{PROJECTS}/{uuid.uuid4()}")
    assert response.status_code == 401


# ----------------------------------------------------------------------- create
def test_create_project(client: TestClient, alice: dict[str, str]) -> None:
    data = create_project(client, alice)

    assert data["name"] == "重生大学时代"
    assert data["genre"] == "都市"
    assert data["style"] == "国漫"
    assert data["status"] == "DRAFT"
    assert data["has_story"] is False
    assert data["story_source"] is None
    assert data["episode_count"] == 0
    assert data["episodes"] == []
    assert data["story_bible_json"] is None
    assert data["created_at"] and data["updated_at"]


def test_create_project_with_story_inline(client: TestClient, alice: dict[str, str]) -> None:
    data = create_project(
        client,
        alice,
        story_source="SYNOPSIS",
        story_text="一个年轻人意外重生回大学时代，决定改变自己的人生。",
    )
    assert data["has_story"] is True
    assert data["story_source"] == "SYNOPSIS"
    assert "重生" in data["story_text"]


def test_create_project_rejects_blank_name(client: TestClient, alice: dict[str, str]) -> None:
    response = client.post(PROJECTS, json={"name": "   "}, headers=alice)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_create_project_rejects_story_without_source(
    client: TestClient, alice: dict[str, str]
) -> None:
    """故事文本 must declare 故事来源 (PRD section 5.2)."""
    response = client.post(
        PROJECTS,
        json={"name": "缺来源", "story_text": "有文本但没有来源"},
        headers=alice,
    )
    assert response.status_code == 422


def test_create_project_trims_name(client: TestClient, alice: dict[str, str]) -> None:
    data = create_project(client, alice, name="  两边有空格  ")
    assert data["name"] == "两边有空格"


# ------------------------------------------------------------------------- read
def test_get_project_detail(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    response = client.get(f"{PROJECTS}/{created['id']}", headers=alice)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == created["id"]
    assert data["episodes"] == []
    assert data["story_text"] is None


def test_get_missing_project_returns_404(client: TestClient, alice: dict[str, str]) -> None:
    response = client.get(f"{PROJECTS}/{uuid.uuid4()}", headers=alice)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_list_is_scoped_to_the_current_user(
    client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    create_project(client, alice, name="Alice 的项目")
    create_project(client, bob, name="Bob 的项目")

    alice_items = client.get(PROJECTS, headers=alice).json()["data"]["items"]
    bob_items = client.get(PROJECTS, headers=bob).json()["data"]["items"]

    assert [item["name"] for item in alice_items] == ["Alice 的项目"]
    assert [item["name"] for item in bob_items] == ["Bob 的项目"]


def test_list_is_empty_for_new_user(client: TestClient, alice: dict[str, str]) -> None:
    body = client.get(PROJECTS, headers=alice).json()
    assert body["data"]["items"] == []
    assert body["meta"]["total"] == 0
    assert body["meta"]["pages"] == 0


def test_list_pagination_meta(client: TestClient, alice: dict[str, str]) -> None:
    for index in range(5):
        create_project(client, alice, name=f"项目 {index}")

    body = client.get(PROJECTS, params={"page": 1, "page_size": 2}, headers=alice).json()
    assert len(body["data"]["items"]) == 2
    assert body["meta"] == {"total": 5, "page": 1, "page_size": 2, "pages": 3}

    second = client.get(PROJECTS, params={"page": 3, "page_size": 2}, headers=alice).json()
    assert len(second["data"]["items"]) == 1


def test_list_search_filters_by_name(client: TestClient, alice: dict[str, str]) -> None:
    create_project(client, alice, name="重生大学时代")
    create_project(client, alice, name="星际迷航")

    body = client.get(PROJECTS, params={"search": "重生"}, headers=alice).json()
    assert body["meta"]["total"] == 1
    assert body["data"]["items"][0]["name"] == "重生大学时代"


def test_list_filters_by_status(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice, name="待归档")
    client.patch(f"{PROJECTS}/{created['id']}", json={"status": "ARCHIVED"}, headers=alice)

    archived = client.get(PROJECTS, params={"status": "ARCHIVED"}, headers=alice).json()
    assert archived["meta"]["total"] == 1

    drafts = client.get(PROJECTS, params={"status": "DRAFT"}, headers=alice).json()
    assert drafts["meta"]["total"] == 0


def test_list_rejects_invalid_page_size(client: TestClient, alice: dict[str, str]) -> None:
    assert client.get(PROJECTS, params={"page_size": 0}, headers=alice).status_code == 422
    assert client.get(PROJECTS, params={"page_size": 500}, headers=alice).status_code == 422


# ----------------------------------------------------------------------- update
def test_update_project_partial(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    response = client.patch(f"{PROJECTS}/{created['id']}", json={"name": "新名字"}, headers=alice)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["name"] == "新名字"
    assert data["genre"] == "都市"  # untouched


def test_update_project_status(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    data = client.patch(
        f"{PROJECTS}/{created['id']}", json={"status": "ACTIVE"}, headers=alice
    ).json()["data"]
    assert data["status"] == "ACTIVE"


def test_update_rejects_empty_payload(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    response = client.patch(f"{PROJECTS}/{created['id']}", json={}, headers=alice)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_update_rejects_invalid_status(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    response = client.patch(f"{PROJECTS}/{created['id']}", json={"status": "NOPE"}, headers=alice)
    assert response.status_code == 422


def test_update_missing_project_returns_404(client: TestClient, alice: dict[str, str]) -> None:
    response = client.patch(f"{PROJECTS}/{uuid.uuid4()}", json={"name": "x"}, headers=alice)
    assert response.status_code == 404


# ----------------------------------------------------------------------- delete
def test_delete_project(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)

    response = client.delete(f"{PROJECTS}/{created['id']}", headers=alice)
    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True

    assert client.get(f"{PROJECTS}/{created['id']}", headers=alice).status_code == 404
    assert client.get(PROJECTS, headers=alice).json()["meta"]["total"] == 0


def test_delete_twice_returns_404(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    client.delete(f"{PROJECTS}/{created['id']}", headers=alice)
    assert client.delete(f"{PROJECTS}/{created['id']}", headers=alice).status_code == 404


# ------------------------------------------------------------------------ story
def test_save_and_read_story(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    story_text = "一个年轻人意外重生回大学时代，决定改变自己的人生。"

    saved = client.post(
        f"{PROJECTS}/{created['id']}/story",
        json={"story_source": "NOVEL", "story_text": story_text},
        headers=alice,
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["has_story"] is True
    assert saved.json()["data"]["story_source"] == "NOVEL"

    fetched = client.get(f"{PROJECTS}/{created['id']}/story", headers=alice).json()["data"]
    assert fetched["story_text"] == story_text
    assert fetched["story_source"] == "NOVEL"
    assert fetched["has_story"] is True


def test_save_story_replaces_previous(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice, story_source="SYNOPSIS", story_text="旧的故事")
    client.post(
        f"{PROJECTS}/{created['id']}/story",
        json={"story_source": "SCRIPT", "story_text": "新的故事"},
        headers=alice,
    )
    fetched = client.get(f"{PROJECTS}/{created['id']}/story", headers=alice).json()["data"]
    assert fetched["story_text"] == "新的故事"
    assert fetched["story_source"] == "SCRIPT"


def test_save_story_rejects_blank_text(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice)
    response = client.post(
        f"{PROJECTS}/{created['id']}/story",
        json={"story_source": "SYNOPSIS", "story_text": "   "},
        headers=alice,
    )
    assert response.status_code == 422


def test_clear_story(client: TestClient, alice: dict[str, str]) -> None:
    created = create_project(client, alice, story_source="SYNOPSIS", story_text="要清空的故事")
    response = client.delete(f"{PROJECTS}/{created['id']}/story", headers=alice)

    assert response.status_code == 200
    assert response.json()["data"]["has_story"] is False

    fetched = client.get(f"{PROJECTS}/{created['id']}/story", headers=alice).json()["data"]
    assert fetched["story_text"] is None
    assert fetched["story_source"] is None


# ------------------------------------------------------------------- isolation
def test_other_users_project_is_invisible(
    client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    """Bob probing Alice's project must get 404, not 403 -- ids stay unguessable."""
    alice_project = create_project(client, alice)

    response = client.get(f"{PROJECTS}/{alice_project['id']}", headers=bob)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_other_user_cannot_update_project(
    client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    alice_project = create_project(client, alice, name="Alice 原名")

    assert (
        client.patch(
            f"{PROJECTS}/{alice_project['id']}", json={"name": "被篡改"}, headers=bob
        ).status_code
        == 404
    )

    # Alice's project is untouched.
    assert (
        client.get(f"{PROJECTS}/{alice_project['id']}", headers=alice).json()["data"]["name"]
        == "Alice 原名"
    )


def test_other_user_cannot_delete_project(
    client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    alice_project = create_project(client, alice)

    assert client.delete(f"{PROJECTS}/{alice_project['id']}", headers=bob).status_code == 404
    assert client.get(f"{PROJECTS}/{alice_project['id']}", headers=alice).status_code == 200


def test_other_user_cannot_write_story(
    client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    alice_project = create_project(client, alice)

    response = client.post(
        f"{PROJECTS}/{alice_project['id']}/story",
        json={"story_source": "SYNOPSIS", "story_text": "入侵者的故事"},
        headers=bob,
    )
    assert response.status_code == 404

    fetched = client.get(f"{PROJECTS}/{alice_project['id']}/story", headers=alice).json()["data"]
    assert fetched["story_text"] is None


def test_other_user_cannot_read_story(
    client: TestClient, alice: dict[str, str], bob: dict[str, str]
) -> None:
    alice_project = create_project(client, alice, story_source="SYNOPSIS", story_text="机密故事")

    response = client.get(f"{PROJECTS}/{alice_project['id']}/story", headers=bob)
    assert response.status_code == 404
    assert "机密故事" not in response.text
