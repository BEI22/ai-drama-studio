"""Episode API tests (PRD sections 22, 27, 38).

End-to-end through the real HTTP surface with the offline mock provider, so the
whole Phase 4 chain (plan -> script -> storyboard -> shots) is exercised without
a network. Assertions focus on the three things that would actually hurt a user:

* **Guards.** Generating a script for an unanalyzed project, re-planning over an
  existing plan, or storyboarding before a script exists must all be refused
  rather than silently doing damage.
* **Id binding.** Every id leaving the API must resolve to a real row (PRD
  section 10), and the response must carry the lookup the UI needs.
* **Isolation.** Episodes belong to a project which belongs to a user; a missing
  join in a query would leak another user's work.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

REGISTER = "/api/v1/auth/register"
PASSWORD = "episodetime2026"

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
)


# --------------------------------------------------------------------- helpers
def _auth(client: TestClient, email: str) -> str:
    response = client.post(REGISTER, json={"email": email, "password": PASSWORD})
    assert response.status_code in (200, 201), response.text
    return response.json()["data"]["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def token(client: TestClient) -> str:
    return _auth(client, "episode@example.com")


@pytest.fixture
def other_token(client: TestClient) -> str:
    return _auth(client, "intruder@example.com")


def _project(client: TestClient, token: str) -> str:
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "重生：分集",
            "genre": "都市",
            "style": "国漫",
            "story_source": "SYNOPSIS",
            "story_text": STORY,
        },
        headers=_headers(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _data(response) -> dict:
    assert response.status_code < 300, response.text
    return response.json()["data"]


def _error_code(response) -> str | None:
    body = response.json()
    return (body.get("error") or {}).get("code")


@pytest.fixture
def analyzed_project(client: TestClient, token: str) -> str:
    """A project that has been through the Phase 3 Story Agent."""
    project_id = _project(client, token)
    response = client.post(f"/api/v1/projects/{project_id}/analyze", headers=_headers(token))
    _data(response)
    return project_id


@pytest.fixture
def planned_episode(client: TestClient, token: str, analyzed_project: str) -> tuple[str, str]:
    response = client.post(
        f"/api/v1/projects/{analyzed_project}/episodes/plan",
        headers=_headers(token),
        params={"episode_count": 3},
    )
    items = _data(response)["items"]
    return analyzed_project, items[0]["id"]


@pytest.fixture
def scripted_episode(
    client: TestClient, token: str, planned_episode: tuple[str, str]
) -> tuple[str, str]:
    _, episode_id = planned_episode
    client.post(f"/api/v1/episodes/{episode_id}/script/generate", headers=_headers(token))
    return planned_episode


# ---------------------------------------------------------------------- guards
class TestGuards:
    def test_plan_before_analysis_is_refused(self, client: TestClient, token: str):
        project_id = _project(client, token)
        response = client.post(
            f"/api/v1/projects/{project_id}/episodes/plan", headers=_headers(token)
        )
        assert response.status_code == 409
        assert _error_code(response) == "CONFLICT"

    def test_replan_without_replace_is_refused(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        project_id, _ = planned_episode
        response = client.post(
            f"/api/v1/projects/{project_id}/episodes/plan", headers=_headers(token)
        )
        assert response.status_code == 409
        assert _error_code(response) == "CONFLICT"

    def test_replan_with_replace_succeeds(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        project_id, _ = planned_episode
        response = client.post(
            f"/api/v1/projects/{project_id}/episodes/plan",
            headers=_headers(token),
            params={"replace": True, "episode_count": 2},
        )
        items = _data(response)["items"]
        assert len(items) == 2

    def test_storyboard_before_script_is_refused(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        response = client.post(
            f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
        )
        assert response.status_code == 409
        assert _error_code(response) == "CONFLICT"

    def test_script_generation_needs_analysis(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        """A manual episode on an unanalyzed project still cannot get a script."""
        _, episode_id = planned_episode
        assert episode_id

        unanalyzed = _project(client, token)
        manual = _data(
            client.post(
                f"/api/v1/projects/{unanalyzed}/episodes",
                json={"title": "手写一集"},
                headers=_headers(token),
            )
        )
        response = client.post(
            f"/api/v1/episodes/{manual['id']}/script/generate", headers=_headers(token)
        )
        assert response.status_code == 409
        assert _error_code(response) == "CONFLICT"

    def test_unknown_episode_is_404(self, client: TestClient, token: str):
        response = client.get(f"/api/v1/episodes/{uuid.uuid4()}", headers=_headers(token))
        assert response.status_code == 404

    def test_unknown_shot_is_404(self, client: TestClient, token: str):
        response = client.patch(
            f"/api/v1/shots/{uuid.uuid4()}", json={"duration": 5}, headers=_headers(token)
        )
        assert response.status_code == 404

    def test_unauthenticated_is_401(self, client: TestClient, analyzed_project: str):
        response = client.get(f"/api/v1/projects/{analyzed_project}/episodes")
        assert response.status_code == 401


# -------------------------------------------------------------------- planning
class TestPlanning:
    def test_plan_creates_labelled_episodes(
        self, client: TestClient, token: str, analyzed_project: str
    ):
        payload = _data(
            client.post(
                f"/api/v1/projects/{analyzed_project}/episodes/plan",
                headers=_headers(token),
                params={"episode_count": 3},
            )
        )
        items = payload["items"]
        assert items, "planner produced no episodes"
        assert [e["episode_number"] for e in items] == list(range(1, len(items) + 1))
        assert all(e["title"] for e in items)
        assert all(e["duration"] > 0 for e in items)
        assert all(e["script_status"] == "NOT_GENERATED" for e in items)
        assert all(e["storyboard_status"] == "NOT_GENERATED" for e in items)
        assert payload["plan_meta"]["model"], "plan provenance must be recorded"

    def test_plan_meta_survives_a_reread(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        """Regression guard for the JSON-column rewrite: read it back fresh.

        The Story Bible's own ``_meta`` must survive the episode-plan metadata
        being written into the same column -- and vice versa.
        """
        project_id, _ = planned_episode
        payload = _data(
            client.get(f"/api/v1/projects/{project_id}/episodes", headers=_headers(token))
        )
        assert payload["plan_meta"]["model"]

        bible = _data(client.get(f"/api/v1/projects/{project_id}/bible", headers=_headers(token)))
        assert bible["meta"]["model"], "the analysis provenance was clobbered"
        assert bible["story_bible"]["title"]

    def test_delete_all_episodes(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        project_id, _ = planned_episode
        payload = _data(
            client.delete(f"/api/v1/projects/{project_id}/episodes", headers=_headers(token))
        )
        assert payload["deleted"] >= 1

        remaining = _data(
            client.get(f"/api/v1/projects/{project_id}/episodes", headers=_headers(token))
        )
        assert remaining["items"] == []

    def test_invalid_episode_count_is_rejected(
        self, client: TestClient, token: str, analyzed_project: str
    ):
        response = client.post(
            f"/api/v1/projects/{analyzed_project}/episodes/plan",
            headers=_headers(token),
            params={"episode_count": 99},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------- script
class TestScript:
    def test_generate_binds_ids_and_returns_the_lookup(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        project_id, episode_id = scripted_episode
        payload = _data(
            client.post(f"/api/v1/episodes/{episode_id}/script/generate", headers=_headers(token))
        )

        script = payload["script"]
        lookup = payload["characters"]
        assert script["scenes"], "script has no scenes"
        assert [s["scene_id"] for s in script["scenes"]] == [
            f"S{i}" for i in range(1, len(script["scenes"]) + 1)
        ]

        # PRD section 10: every dialogue speaker binds to a real Character Bible
        # row, and the response carries the id -> name lookup the UI renders with.
        known_characters = {
            c["id"]
            for c in _data(
                client.get(f"/api/v1/projects/{project_id}/characters", headers=_headers(token))
            )
        }
        known_locations = {
            loc["id"]
            for loc in _data(
                client.get(f"/api/v1/projects/{project_id}/locations", headers=_headers(token))
            )
        }

        for scene in script["scenes"]:
            assert scene["location_id"] in known_locations, scene["location_id"]
            for character_id in scene.get("characters") or []:
                assert character_id in known_characters, character_id
            for line in scene.get("dialogues") or []:
                assert line["character_id"] in known_characters, line
                assert line["character_id"] in lookup, "missing from the id->name lookup"

        assert lookup, "the id->name lookup must not be empty"
        assert payload["meta"]["provider"]

    def test_script_status_is_reported(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        payload = _data(
            client.get(f"/api/v1/episodes/{episode_id}/script", headers=_headers(token))
        )
        assert payload["script_status"] == "SUCCEEDED"
        assert payload["has_script"] is True

        episode = _data(client.get(f"/api/v1/episodes/{episode_id}", headers=_headers(token)))
        assert episode["has_script"] is True

    def test_script_before_generation_is_empty_not_an_error(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        payload = _data(
            client.get(f"/api/v1/episodes/{episode_id}/script", headers=_headers(token))
        )
        assert payload["script"] is None
        assert payload["has_script"] is False
        assert payload["script_status"] == "NOT_GENERATED"

    def test_patch_script(self, client: TestClient, token: str, scripted_episode: tuple[str, str]):
        _, episode_id = scripted_episode
        response = client.patch(
            f"/api/v1/episodes/{episode_id}/script",
            json={"summary": "手工改写"},
            headers=_headers(token),
        )
        assert _data(response)["script"]["summary"] == "手工改写"

    def test_patch_script_on_missing_script_is_404(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        response = client.patch(
            f"/api/v1/episodes/{episode_id}/script",
            json={"summary": "还没有剧本"},
            headers=_headers(token),
        )
        assert response.status_code == 404

    def test_empty_patch_is_rejected(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        response = client.patch(
            f"/api/v1/episodes/{episode_id}/script", json={}, headers=_headers(token)
        )
        # ValidationError maps to 422 in this codebase (app/core/exceptions.py).
        assert response.status_code == 422


# ------------------------------------------------------------------ storyboard
class TestStoryboard:
    def test_generate_persists_shots_in_absolute_order(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        payload = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )

        shots = payload["shots"]
        assert shots, "no shots were persisted"
        assert [s["sequence"] for s in shots] == list(range(1, len(shots) + 1))

        # shot_number restarts at 1 inside every scene, while sequence does not.
        per_scene: dict[str, list[int]] = {}
        for shot in shots:
            per_scene.setdefault(shot["scene_id"], []).append(shot["shot_number"])
        for scene_id, numbers in per_scene.items():
            assert numbers == list(range(1, len(numbers) + 1)), scene_id

        assert payload["storyboard_status"] == "SUCCEEDED"

    def test_storyboard_covers_every_script_scene(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        script = _data(client.get(f"/api/v1/episodes/{episode_id}/script", headers=_headers(token)))
        payload = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )

        assert [s["scene_id"] for s in payload["storyboard"]["scenes"]] == [
            s["scene_id"] for s in script["script"]["scenes"]
        ]

    def test_shot_vocabularies_are_closed(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        payload = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        sizes = {s["shot_size"] for s in payload["shots"]}
        moves = {s["camera_movement"] for s in payload["shots"]}
        assert sizes <= {
            "extreme_wide",
            "wide",
            "medium",
            "medium_close_up",
            "close_up",
            "extreme_close_up",
        }, sizes
        assert moves <= {
            "static",
            "slow_push",
            "push_in",
            "pull_out",
            "pan_left",
            "pan_right",
            "tilt_up",
            "tilt_down",
            "tracking",
            "crane",
            "handheld",
        }, moves

    def test_list_shots_matches_the_storyboard(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        payload = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        listed = _data(client.get(f"/api/v1/episodes/{episode_id}/shots", headers=_headers(token)))
        assert len(listed) == len(payload["shots"])

    def test_patch_shot(self, client: TestClient, token: str, scripted_episode: tuple[str, str]):
        _, episode_id = scripted_episode
        payload = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        shot_id = payload["shots"][0]["id"]

        updated = _data(
            client.patch(
                f"/api/v1/shots/{shot_id}",
                json={"duration": 9, "camera_movement": "crane", "characters": ["林澈"]},
                headers=_headers(token),
            )
        )
        assert updated["duration"] == 9
        assert updated["camera_movement"] == "crane"
        assert updated["characters"] == ["林澈"]

    def test_patch_shot_rejects_an_unknown_vocabulary_value(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        """User input is rejected, not silently coerced onto a default.

        ``ShotDraft`` (model output) coerces; ``ShotUpdate`` (a human's edit) must
        not, otherwise the user is shown something they did not choose.
        """
        _, episode_id = scripted_episode
        payload = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        shot_id = payload["shots"][0]["id"]

        for bad_field, bad_value in (("shot_size", "超宽幅"), ("camera_movement", "旋转环绕")):
            response = client.patch(
                f"/api/v1/shots/{shot_id}", json={bad_field: bad_value}, headers=_headers(token)
            )
            assert response.status_code == 422, f"{bad_field} accepted {bad_value!r}"

        # A valid value still works, so the validation is not simply broken.
        ok = client.patch(
            f"/api/v1/shots/{shot_id}", json={"shot_size": "close_up"}, headers=_headers(token)
        )
        assert _data(ok)["shot_size"] == "close_up"

    def test_patch_shot_accepts_a_pinyin_alias_for_shot_size(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        """The canonical enum values are what the UI sends, and they work."""
        _, episode_id = scripted_episode
        payload = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        for size in ("extreme_wide", "medium", "extreme_close_up"):
            response = client.patch(
                f"/api/v1/shots/{payload['shots'][0]['id']}",
                json={"shot_size": size},
                headers=_headers(token),
            )
            assert _data(response)["shot_size"] == size

    def test_storyboard_status_before_generation(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        payload = _data(
            client.get(f"/api/v1/episodes/{episode_id}/storyboard", headers=_headers(token))
        )
        assert payload["storyboard"] is None
        assert payload["shots"] == []
        assert payload["storyboard_status"] == "NOT_GENERATED"


# --------------------------------------------------------------- regeneration
class TestRegeneration:
    def test_new_script_invalidates_the_storyboard(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        """Stale shots must go, not linger pointing at scenes that changed.

        Phases 5-7 hang generated media off shot rows, so keeping old shots
        attached to new content would silently mis-associate every asset.
        """
        _, episode_id = scripted_episode
        client.post(f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token))

        client.post(f"/api/v1/episodes/{episode_id}/script/generate", headers=_headers(token))

        payload = _data(
            client.get(f"/api/v1/episodes/{episode_id}/storyboard", headers=_headers(token))
        )
        assert payload["storyboard_status"] == "NOT_GENERATED"
        assert payload["has_storyboard"] is False
        assert payload["shots"] == [], "stale shots survived a script regeneration"

    def test_storyboard_regeneration_replaces_shots(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        first = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        second = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )

        assert len(second["shots"]) == len(first["shots"])
        assert {s["id"] for s in second["shots"]}.isdisjoint({s["id"] for s in first["shots"]}), (
            "shots should be rebuilt, not reused by id"
        )


# ---------------------------------------------------------------- consistency
class TestConsistencyEndpoint:
    def test_clean_report_matches_generation_time(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        """The re-check must not disagree with the report stored at generation.

        Regression guard: re-checking only the storyboard used to drop the
        script-stage findings, so the two reports could differ.
        """
        _, episode_id = scripted_episode
        generated = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        recheck = _data(
            client.get(f"/api/v1/episodes/{episode_id}/consistency", headers=_headers(token))
        )

        generated_codes = sorted(i["code"] for i in generated["consistency"]["issues"])
        recheck_codes = sorted(i["code"] for i in recheck["issues"])
        assert generated_codes == recheck_codes

    def test_report_shape_and_verdict(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        client.post(f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token))
        payload = _data(
            client.get(f"/api/v1/episodes/{episode_id}/consistency", headers=_headers(token))
        )

        assert payload["checked_shots"] > 0
        assert isinstance(payload["ok"], bool)
        assert payload["errors"] == 0, [i for i in payload["issues"] if i["severity"] == "ERROR"]
        assert "UNKNOWN_CHARACTER" not in {i["code"] for i in payload["issues"]}

    def test_consistency_is_available_without_a_storyboard(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        payload = _data(
            client.get(f"/api/v1/episodes/{episode_id}/consistency", headers=_headers(token))
        )
        assert payload["checked_shots"] == 0
        assert isinstance(payload["ok"], bool)


# ------------------------------------------------------------------ episode CRUD
class TestEpisodeCrud:
    def test_manual_episode_gets_the_next_number(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        project_id, _ = planned_episode
        existing = _data(
            client.get(f"/api/v1/projects/{project_id}/episodes", headers=_headers(token))
        )["items"]

        created = _data(
            client.post(
                f"/api/v1/projects/{project_id}/episodes",
                json={"title": "手工新增", "summary": "手写梗概", "duration": 150},
                headers=_headers(token),
            )
        )
        assert created["episode_number"] == len(existing) + 1
        assert created["script_status"] == "NOT_GENERATED"

    def test_duplicate_number_is_refused(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        project_id, _ = planned_episode
        response = client.post(
            f"/api/v1/projects/{project_id}/episodes",
            json={"title": "重复", "episode_number": 1},
            headers=_headers(token),
        )
        assert response.status_code == 409
        assert _error_code(response) == "CONFLICT"

    def test_patch_episode(self, client: TestClient, token: str, planned_episode: tuple[str, str]):
        _, episode_id = planned_episode
        updated = _data(
            client.patch(
                f"/api/v1/episodes/{episode_id}",
                json={"title": "改过标题", "duration": 200},
                headers=_headers(token),
            )
        )
        assert updated["title"] == "改过标题"
        assert updated["duration"] == 200

    def test_patch_rejects_a_clashing_number(
        self, client: TestClient, token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        response = client.patch(
            f"/api/v1/episodes/{episode_id}",
            json={"episode_number": 2},
            headers=_headers(token),
        )
        assert response.status_code == 409

    def test_delete_episode_removes_its_shots(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        client.post(f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token))

        assert (
            client.delete(f"/api/v1/episodes/{episode_id}", headers=_headers(token)).status_code
            < 300
        )
        assert (
            client.get(f"/api/v1/episodes/{episode_id}", headers=_headers(token)).status_code == 404
        )

    def test_list_is_ordered_and_carries_shot_counts(
        self, client: TestClient, token: str, scripted_episode: tuple[str, str]
    ):
        project_id, episode_id = scripted_episode
        client.post(f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token))

        payload = _data(
            client.get(f"/api/v1/projects/{project_id}/episodes", headers=_headers(token))
        )
        numbers = [e["episode_number"] for e in payload["items"]]
        assert numbers == sorted(numbers)

        target = next(e for e in payload["items"] if e["id"] == episode_id)
        assert target["shot_count"] > 0
        assert target["has_storyboard"] is True
        assert payload["totals"]["episodes"] == len(payload["items"])


# ------------------------------------------------------------------- isolation
class TestIsolation:
    def test_episode_list_requires_ownership(
        self, client: TestClient, other_token: str, planned_episode: tuple[str, str]
    ):
        project_id, _ = planned_episode
        response = client.get(
            f"/api/v1/projects/{project_id}/episodes", headers=_headers(other_token)
        )
        assert response.status_code == 404

    def test_episode_read_requires_ownership(
        self, client: TestClient, other_token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        response = client.get(f"/api/v1/episodes/{episode_id}", headers=_headers(other_token))
        assert response.status_code == 404, "another user must not read this episode"

    def test_script_read_requires_ownership(
        self, client: TestClient, other_token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        response = client.get(
            f"/api/v1/episodes/{episode_id}/script", headers=_headers(other_token)
        )
        assert response.status_code == 404

    def test_storyboard_read_requires_ownership(
        self, client: TestClient, other_token: str, scripted_episode: tuple[str, str]
    ):
        _, episode_id = scripted_episode
        response = client.get(
            f"/api/v1/episodes/{episode_id}/storyboard", headers=_headers(other_token)
        )
        assert response.status_code == 404

    def test_generation_requires_ownership(
        self, client: TestClient, other_token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        response = client.post(
            f"/api/v1/episodes/{episode_id}/script/generate", headers=_headers(other_token)
        )
        assert response.status_code == 404

    def test_shot_edit_requires_ownership(
        self, client: TestClient, token: str, other_token: str, scripted_episode: tuple[str, str]
    ):
        """A shot row is reachable by id, so its join to the owner must be checked."""
        _, episode_id = scripted_episode
        owner_view = _data(
            client.post(
                f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token)
            )
        )
        shot_id = owner_view["shots"][0]["id"]

        denied = client.patch(
            f"/api/v1/shots/{shot_id}", json={"duration": 12}, headers=_headers(other_token)
        )
        assert denied.status_code == 404, "another user must not edit this shot"

        # And the owner can still edit it, so the guard is not simply broken.
        allowed = client.patch(
            f"/api/v1/shots/{shot_id}", json={"duration": 6}, headers=_headers(token)
        )
        assert _data(allowed)["duration"] == 6

    def test_cross_user_cannot_plan_on_someone_elses_project(
        self, client: TestClient, other_token: str, analyzed_project: str
    ):
        response = client.post(
            f"/api/v1/projects/{analyzed_project}/episodes/plan", headers=_headers(other_token)
        )
        assert response.status_code == 404

    def test_cross_user_cannot_delete_an_episode(
        self, client: TestClient, other_token: str, planned_episode: tuple[str, str]
    ):
        _, episode_id = planned_episode
        response = client.delete(f"/api/v1/episodes/{episode_id}", headers=_headers(other_token))
        assert response.status_code == 404
