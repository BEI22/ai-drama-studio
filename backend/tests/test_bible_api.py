"""Story Agent + Bible API tests (PRD sections 22, 27, 37).

The critical assertions are the isolation ones: characters and locations belong
to a project, so an ownership check must traverse that join. A bug there would let
one user read or edit another user's cast.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
PASSWORD = "storytime2026"

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
)


# --------------------------------------------------------------------- helpers
def _auth(client: TestClient, email: str = "alice@example.com") -> str:
    response = client.post(REGISTER, json={"email": email, "password": PASSWORD})
    if response.status_code == 409:
        response = client.post(LOGIN, json={"email": email, "password": PASSWORD})
    assert response.status_code in (200, 201), response.text
    return response.json()["data"]["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _project(client: TestClient, token: str, **overrides) -> dict:
    payload = {
        "name": "重生",
        "genre": "都市",
        "style": "国漫",
        "story_source": "SYNOPSIS",
        "story_text": STORY,
    }
    payload.update(overrides)
    response = client.post("/api/v1/projects", json=payload, headers=_headers(token))
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _analyze(client: TestClient, token: str, project_id: str, **params) -> dict:
    response = client.post(
        f"/api/v1/projects/{project_id}/analyze", headers=_headers(token), params=params
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.fixture
def token(client: TestClient) -> str:
    return _auth(client)


@pytest.fixture
def project(client: TestClient, token: str) -> dict:
    return _project(client, token)


@pytest.fixture
def analyzed(client: TestClient, token: str, project: dict) -> dict:
    return _analyze(client, token, project["id"])


# ------------------------------------------------------------------- analyze
class TestAnalyze:
    def test_analyze_returns_the_full_bible(self, client, token, project) -> None:
        bible = _analyze(client, token, project["id"])
        assert bible["analysis_status"] == "SUCCEEDED"
        assert bible["story_bible"]["title"]
        assert len(bible["characters"]) >= 3
        assert len(bible["locations"]) >= 3

    def test_analyze_marks_mock_provenance(self, client, token, project) -> None:
        """Output must never pass itself off as a real model's work."""
        bible = _analyze(client, token, project["id"])
        assert bible["meta"]["mock"] is True
        assert bible["meta"]["provider"] == "mock"
        assert bible["meta"]["prompt_versions"]["story_parser"] == "story_parser_v2"

    def test_analyze_records_usage_for_cost_tracking(self, client, token, project) -> None:
        bible = _analyze(client, token, project["id"])
        assert len(bible["meta"]["usage"]) == 3

    def test_characters_are_extracted(self, client, analyzed) -> None:
        names = [c["name"] for c in analyzed["characters"]]
        assert "林澈" in names
        assert names[0] == "林澈"

    def test_characters_carry_the_character_bible_fields(self, client, analyzed) -> None:
        hero = analyzed["characters"][0]
        for field in (
            "id",
            "name",
            "role",
            "age",
            "gender",
            "description",
            "appearance",
            "hair",
            "clothing",
            "personality",
            "voice_id",
            "reference_image_url",
        ):
            assert field in hero, field

    def test_locations_carry_the_scene_bible_fields(self, client, analyzed) -> None:
        scene = analyzed["locations"][0]
        for field in (
            "id",
            "name",
            "description",
            "time",
            "lighting",
            "visual_style",
            "reference_image_url",
        ):
            assert field in scene, field

    def test_project_detail_reflects_the_analysis(self, client, token, project, analyzed) -> None:
        detail = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(token)).json()[
            "data"
        ]
        assert detail["analysis_status"] == "SUCCEEDED"
        assert detail["analyzed_at"] is not None
        assert detail["character_count"] == len(analyzed["characters"])
        assert detail["location_count"] == len(analyzed["locations"])

    def test_project_list_surfaces_counts(self, client, token, project, analyzed) -> None:
        listed = client.get("/api/v1/projects", headers=_headers(token)).json()["data"]["items"]
        row = next(item for item in listed if item["id"] == project["id"])
        assert row["character_count"] >= 3
        assert row["analysis_status"] == "SUCCEEDED"

    def test_second_analyze_without_replace_is_a_conflict(
        self, client, token, project, analyzed
    ) -> None:
        response = client.post(f"/api/v1/projects/{project['id']}/analyze", headers=_headers(token))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_second_analyze_with_replace_succeeds(self, client, token, project, analyzed) -> None:
        second = _analyze(client, token, project["id"], replace="true")
        assert len(second["characters"]) == len(analyzed["characters"])

    def test_replace_keeps_character_ids_stable(self, client, token, project, analyzed) -> None:
        """Phase 4 shots will reference these ids, so they must not churn."""
        before = {c["name"]: c["id"] for c in analyzed["characters"]}
        after = {
            c["name"]: c["id"]
            for c in _analyze(client, token, project["id"], replace="true")["characters"]
        }
        for name, identifier in before.items():
            assert after[name] == identifier

    def test_analyze_without_story_is_a_validation_error(self, client, token) -> None:
        project = _project(client, token, story_source=None, story_text=None)
        response = client.post(f"/api/v1/projects/{project['id']}/analyze", headers=_headers(token))
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_analyze_with_preview_text_does_not_save_it(self, client, token, project) -> None:
        """``story_text`` previews a candidate without mutating the project."""
        project = _project(client, token, story_source=None, story_text=None)
        response = client.post(
            f"/api/v1/projects/{project['id']}/analyze",
            headers=_headers(token),
            json={"story_text": STORY},
        )
        assert response.status_code == 200
        detail = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(token)).json()[
            "data"
        ]
        assert detail["story_text"] is None

    def test_analyze_requires_auth(self, client, project) -> None:
        assert client.post(f"/api/v1/projects/{project['id']}/analyze").status_code == 401

    def test_analyze_status_before_running(self, client, token, project) -> None:
        status = client.get(
            f"/api/v1/projects/{project['id']}/analyze/status", headers=_headers(token)
        ).json()["data"]
        assert status["analysis_status"] == "NOT_ANALYZED"
        assert status["characters"] == 0
        assert status["provider"] == "mock"

    def test_analyze_status_after_running(self, client, token, project, analyzed) -> None:
        status = client.get(
            f"/api/v1/projects/{project['id']}/analyze/status", headers=_headers(token)
        ).json()["data"]
        assert status["analysis_status"] == "SUCCEEDED"
        assert status["characters"] >= 3

    def test_saving_a_new_story_invalidates_the_analysis(
        self, client, token, project, analyzed
    ) -> None:
        """Otherwise the Bible silently describes a story that no longer exists."""
        response = client.post(
            f"/api/v1/projects/{project['id']}/story",
            headers=_headers(token),
            json={"story_source": "NOVEL", "story_text": "完全不同的一段新故事内容。"},
        )
        assert response.json()["data"]["analysis_status"] == "NOT_ANALYZED"


# ---------------------------------------------------------------- bible read
class TestBible:
    def test_bible_before_analysis_is_null_not_an_error(self, client, token, project) -> None:
        bible = client.get(
            f"/api/v1/projects/{project['id']}/bible", headers=_headers(token)
        ).json()["data"]
        assert bible["story_bible"] is None
        assert bible["analysis_status"] == "NOT_ANALYZED"
        assert bible["characters"] == []
        assert bible["locations"] == []

    def test_bible_after_analysis(self, client, token, project, analyzed) -> None:
        bible = client.get(
            f"/api/v1/projects/{project['id']}/bible", headers=_headers(token)
        ).json()["data"]
        assert bible["story_bible"]["title"]
        assert len(bible["characters"]) >= 3

    def test_bible_requires_auth(self, client, project) -> None:
        assert client.get(f"/api/v1/projects/{project['id']}/bible").status_code == 401

    def test_bible_for_unknown_project_is_404(self, client, token) -> None:
        import uuid

        response = client.get(f"/api/v1/projects/{uuid.uuid4()}/bible", headers=_headers(token))
        assert response.status_code == 404


# --------------------------------------------------------------- characters
class TestCharacterCrud:
    def test_list_is_empty_before_analysis(self, client, token, project) -> None:
        response = client.get(
            f"/api/v1/projects/{project['id']}/characters", headers=_headers(token)
        )
        assert response.json()["data"] == []

    def test_create_manual_character(self, client, token, project) -> None:
        response = client.post(
            f"/api/v1/projects/{project['id']}/characters",
            headers=_headers(token),
            json={"name": "手动角色", "role": "MENTOR", "appearance": "银发老者"},
        )
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["name"] == "手动角色"
        assert body["role"] == "MENTOR"
        assert body["sort_order"] == 1

    def test_duplicate_name_is_rejected(self, client, token, project) -> None:
        payload = {"name": "重复角色"}
        client.post(
            f"/api/v1/projects/{project['id']}/characters", headers=_headers(token), json=payload
        )
        response = client.post(
            f"/api/v1/projects/{project['id']}/characters", headers=_headers(token), json=payload
        )
        assert response.status_code == 409

    def test_update_character(self, client, token, project, analyzed) -> None:
        """PRD section 37 item 17: the user can modify extracted characters."""
        character_id = analyzed["characters"][0]["id"]
        response = client.patch(
            f"/api/v1/characters/{character_id}",
            headers=_headers(token),
            json={"appearance": "用户重写的外貌", "role": "ANTAGONIST"},
        )
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["appearance"] == "用户重写的外貌"
        assert body["role"] == "ANTAGONIST"

    def test_update_is_partial(self, client, token, project, analyzed) -> None:
        character = analyzed["characters"][0]
        body = client.patch(
            f"/api/v1/characters/{character['id']}",
            headers=_headers(token),
            json={"appearance": "只改外貌"},
        ).json()["data"]
        assert body["appearance"] == "只改外貌"
        assert body["name"] == character["name"]

    def test_update_with_unknown_field_is_rejected(self, client, token, analyzed) -> None:
        response = client.patch(
            f"/api/v1/characters/{analyzed['characters'][0]['id']}",
            headers=_headers(token),
            json={"nmae": "typo"},
        )
        assert response.status_code == 422

    def test_update_with_empty_body_is_rejected(self, client, token, analyzed) -> None:
        response = client.patch(
            f"/api/v1/characters/{analyzed['characters'][0]['id']}",
            headers=_headers(token),
            json={},
        )
        assert response.status_code == 422

    def test_rename_to_an_existing_name_is_rejected(self, client, token, analyzed) -> None:
        first, second = analyzed["characters"][0], analyzed["characters"][1]
        response = client.patch(
            f"/api/v1/characters/{first['id']}",
            headers=_headers(token),
            json={"name": second["name"]},
        )
        assert response.status_code == 409

    def test_delete_character(self, client, token, analyzed) -> None:
        character_id = analyzed["characters"][0]["id"]
        assert (
            client.delete(f"/api/v1/characters/{character_id}", headers=_headers(token)).json()[
                "data"
            ]["deleted"]
            is True
        )
        remaining = client.get(
            f"/api/v1/projects/{analyzed['project_id']}/characters", headers=_headers(token)
        ).json()["data"]
        assert character_id not in [item["id"] for item in remaining]

    def test_delete_twice_is_404(self, client, token, analyzed) -> None:
        character_id = analyzed["characters"][0]["id"]
        client.delete(f"/api/v1/characters/{character_id}", headers=_headers(token))
        assert (
            client.delete(f"/api/v1/characters/{character_id}", headers=_headers(token)).status_code
            == 404
        )


# ---------------------------------------------------------------- locations
class TestLocationCrud:
    def test_create_and_update(self, client, token, project) -> None:
        created = client.post(
            f"/api/v1/projects/{project['id']}/locations",
            headers=_headers(token),
            json={"name": "天台", "time": "深夜", "lighting": "城市霓虹"},
        ).json()["data"]
        updated = client.patch(
            f"/api/v1/locations/{created['id']}",
            headers=_headers(token),
            json={"lighting": "无光的深夜"},
        ).json()["data"]
        assert updated["lighting"] == "无光的深夜"
        assert updated["time"] == "深夜"

    def test_duplicate_location_is_rejected(self, client, token, project) -> None:
        payload = {"name": "重复场景"}
        client.post(
            f"/api/v1/projects/{project['id']}/locations", headers=_headers(token), json=payload
        )
        assert (
            client.post(
                f"/api/v1/projects/{project['id']}/locations", headers=_headers(token), json=payload
            ).status_code
            == 409
        )

    def test_delete_location(self, client, token, analyzed) -> None:
        location_id = analyzed["locations"][0]["id"]
        assert (
            client.delete(f"/api/v1/locations/{location_id}", headers=_headers(token)).json()[
                "data"
            ]["deleted"]
            is True
        )


# ---------------------------------------------------------------- isolation
class TestBibleIsolation:
    """Characters/locations hang off a project, so ownership needs a join.

    A missing join would let B read or edit A's cast through a bare id -- these
    tests exist to fail loudly if that ever regresses.
    """

    def test_other_user_cannot_read_characters(self, client, token, analyzed) -> None:
        other = _auth(client, "bob@example.com")
        response = client.get(
            f"/api/v1/projects/{analyzed['project_id']}/characters", headers=_headers(other)
        )
        assert response.status_code == 404
        assert "林澈" not in response.text

    def test_other_user_cannot_read_locations(self, client, token, analyzed) -> None:
        other = _auth(client, "bob@example.com")
        response = client.get(
            f"/api/v1/projects/{analyzed['project_id']}/locations", headers=_headers(other)
        )
        assert response.status_code == 404

    def test_other_user_cannot_read_the_bible(self, client, token, analyzed) -> None:
        other = _auth(client, "bob@example.com")
        response = client.get(
            f"/api/v1/projects/{analyzed['project_id']}/bible", headers=_headers(other)
        )
        assert response.status_code == 404
        assert "林澈" not in response.text

    def test_other_user_cannot_patch_a_character(self, client, token, analyzed) -> None:
        other = _auth(client, "bob@example.com")
        character_id = analyzed["characters"][0]["id"]
        response = client.patch(
            f"/api/v1/characters/{character_id}",
            headers=_headers(other),
            json={"name": "被改坏了"},
        )
        assert response.status_code == 404

        # And the owner's data is untouched.
        still = client.get(
            f"/api/v1/projects/{analyzed['project_id']}/characters", headers=_headers(token)
        ).json()["data"]
        assert "被改坏了" not in [item["name"] for item in still]

    def test_other_user_cannot_delete_a_character(self, client, token, analyzed) -> None:
        other = _auth(client, "bob@example.com")
        character_id = analyzed["characters"][0]["id"]
        assert (
            client.delete(f"/api/v1/characters/{character_id}", headers=_headers(other)).status_code
            == 404
        )

        remaining = client.get(
            f"/api/v1/projects/{analyzed['project_id']}/characters", headers=_headers(token)
        ).json()["data"]
        assert character_id in [item["id"] for item in remaining]

    def test_other_user_cannot_patch_a_location(self, client, token, analyzed) -> None:
        other = _auth(client, "bob@example.com")
        response = client.patch(
            f"/api/v1/locations/{analyzed['locations'][0]['id']}",
            headers=_headers(other),
            json={"name": "被改坏了"},
        )
        assert response.status_code == 404

    def test_other_user_cannot_analyze_someone_elses_project(self, client, token, project) -> None:
        other = _auth(client, "bob@example.com")
        response = client.post(f"/api/v1/projects/{project['id']}/analyze", headers=_headers(other))
        assert response.status_code == 404

    def test_unknown_character_id_is_404(self, client, token) -> None:
        import uuid

        assert (
            client.patch(
                f"/api/v1/characters/{uuid.uuid4()}", headers=_headers(token), json={"name": "x"}
            ).status_code
            == 404
        )

    def test_characters_require_auth(self, client, project) -> None:
        assert client.get(f"/api/v1/projects/{project['id']}/characters").status_code == 401
        assert client.get(f"/api/v1/projects/{project['id']}/locations").status_code == 401


# ------------------------------------------------------------- cascade
class TestCascade:
    def test_deleting_a_project_removes_its_bible_rows(
        self, client, token, project, analyzed
    ) -> None:
        """Otherwise a re-created project could inherit a stranger's cast."""
        project_id = analyzed["project_id"]
        assert (
            client.delete(f"/api/v1/projects/{project_id}", headers=_headers(token)).status_code
            == 200
        )

        # Re-created with the same id is impossible, so assert the rows are gone
        # by checking the project itself no longer resolves.
        assert (
            client.get(f"/api/v1/projects/{project_id}", headers=_headers(token)).status_code == 404
        )

        from app.models.character import Character
        from tests.conftest import SessionLocal

        with SessionLocal() as session:
            assert session.query(Character).count() == 0
