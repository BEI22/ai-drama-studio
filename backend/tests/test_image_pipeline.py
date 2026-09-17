"""Image pipeline tests (PRD sections 19, 21, 22, 25, 27 -- Phase 5).

Three layers, because each can fail independently and only one of them is
observable from the others:

* **Prompt Builder** (unit) -- PRD section 19's six layers must actually reach the
  final text. This is the layer that silently rots if the wording file is edited:
  the pipeline keeps "working" while every prompt quietly loses a layer.
* **Image service / worker** (integration) -- the section 21 state machine,
  idempotency, retry accounting, storage and Asset creation, exercised through the
  real service against SQLite and the offline mock provider.
* **HTTP surface** (end-to-end) -- the section 22 routes, status codes, ownership
  isolation and the envelope.

The suite is hermetic: mock provider, temp storage directory, eager Celery (so the
real enqueue path runs inline) and no network. Every assertion about a produced
image is a statement about real bytes on disk -- the mock writes a valid PNG whose
embedded barcode encodes the SHA-256 of the prompt, so "the picture belongs to this
shot" is checkable rather than assumed.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import ConflictError, NotFoundError, ProviderError
from app.core.signing import sign_storage_url, verify_storage_signature
from app.models.enums import TaskStatus
from app.providers.base import ImageRequest
from app.providers.image.mock import MockImageProvider, prompt_bits
from app.services.image_service import ImageService
from app.services.prompt_builder import (
    CAMERA_MOVEMENT_PROMPT_LABELS,
    SHOT_SIZE_PROMPT_LABELS,
    build_image_prompt,
)
from app.utils.png import decode_png_pixels, decode_png_size

REGISTER = "/api/v1/auth/register"
PASSWORD = "imagetime2026"

STORY = (
    "林澈在大学宿舍的床上睁开眼，发现自己竟然回到了十年前的开学日。"
    "前世他因为沉迷游戏错过保研，毕业后四处碰壁，最后在出租屋里郁郁而终。"
    "这一次，他决定改变自己的人生。室友赵明达推开宿舍门，喊他一起去食堂。"
    "林澈没有说话，只是握紧了拳头。班主任周老师走进教室，宣布了考研的报名时间。"
    "苏晚坐在他旁边的座位上，笑着说：林澈，你这次一定要加油。"
)

CHARACTER = {
    "name": "林澈",
    "appearance": "18岁东亚男性大学生",
    "hair": "黑色短发略带蓬松碎发",
    "clothing": "白色短袖T恤外搭浅蓝色衬衫",
    "reference_image_url": None,
}
LOCATION = {
    "name": "大学礼堂",
    "description": "现代大学室内大礼堂，阶梯式红色软座椅排列整齐",
    "lighting": "礼堂顶部大灯明亮，舞台聚光灯打在主席台上",
    "visual_style": "低饱和冷色调",
    "reference_image_url": None,
}
SHOT = {
    "shot_size": "medium_close_up",
    "camera_movement": "slow_push",
    "expression": "恍惚失神",
    "action": "脸贴在摊开的新生手册上",
    "visual_description": "林澈歪在红色软座椅上打盹",
    "image_prompt": "旧的 LLM 提示词，不应被当作核心",
}


# --------------------------------------------------------------------- helpers
def _auth(client: TestClient, email: str) -> str:
    response = client.post(REGISTER, json={"email": email, "password": PASSWORD})
    assert response.status_code in (200, 201), response.text
    return response.json()["data"]["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _data(response) -> dict:
    assert response.status_code < 300, response.text
    return response.json()["data"]


def _error_code(response) -> str | None:
    body = response.json()
    return (body.get("error") or {}).get("code")


@pytest.fixture
def token(client: TestClient) -> str:
    return _auth(client, "image@example.com")


@pytest.fixture
def other_token(client: TestClient) -> str:
    return _auth(client, "image-intruder@example.com")


@pytest.fixture
def storyboarded(client: TestClient, token: str) -> tuple[str, str, str]:
    """A project taken all the way to a storyboard: (project, episode, shot)."""
    project_id = _data(
        client.post(
            "/api/v1/projects",
            json={
                "name": "重生：图片",
                "genre": "都市",
                "style": "国漫",
                "story_source": "SYNOPSIS",
                "story_text": STORY,
            },
            headers=_headers(token),
        )
    )["id"]
    _data(client.post(f"/api/v1/projects/{project_id}/analyze", headers=_headers(token)))
    episode_id = _data(
        client.post(
            f"/api/v1/projects/{project_id}/episodes/plan",
            headers=_headers(token),
            params={"episode_count": 2},
        )
    )["items"][0]["id"]
    client.post(f"/api/v1/episodes/{episode_id}/script/generate", headers=_headers(token))
    shots = _data(
        client.post(f"/api/v1/episodes/{episode_id}/storyboard/generate", headers=_headers(token))
    )["shots"]
    assert shots, "storyboard must produce at least one shot"
    return project_id, episode_id, shots[0]["id"]


# ============================================================ Prompt Builder
class TestPromptBuilder:
    """PRD section 19: every layer must reach the finished prompt."""

    def test_all_six_layers_reach_the_prompt(self):
        built = build_image_prompt(
            project_style="国漫",
            bible_style="都市校园风",
            characters=[CHARACTER],
            location=LOCATION,
            shot=SHOT,
        )
        # System Style, Character Description, Location Description (+lighting),
        # Current Shot, Camera, Emotion -- section 19's list.
        assert "国漫" in built.prompt
        assert "都市校园风" in built.prompt
        assert CHARACTER["hair"] in built.prompt
        assert CHARACTER["clothing"] in built.prompt
        assert LOCATION["description"] in built.prompt
        assert LOCATION["lighting"] in built.prompt
        assert SHOT["visual_description"] in built.prompt
        assert SHOT_SIZE_PROMPT_LABELS["medium_close_up"] in built.prompt
        assert CAMERA_MOVEMENT_PROMPT_LABELS["slow_push"] in built.prompt
        assert SHOT["expression"] in built.prompt

    def test_visual_description_is_the_core_not_the_stale_llm_prompt(self):
        built = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[CHARACTER],
            location=LOCATION,
            shot=SHOT,
        )
        assert built.core_source == "visual_description"
        assert SHOT["image_prompt"] not in built.prompt

    def test_core_falls_back_in_a_defined_order(self):
        """visual_description -> action -> LLM image_prompt -> nothing.

        ``core_source`` must name the layer that actually won: an empty value would
        make a bad picture untraceable.
        """
        no_description = {**SHOT, "visual_description": None}
        from_action = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[],
            location=None,
            shot=no_description,
        )
        assert from_action.core_source == "action"
        assert no_description["action"] in from_action.prompt

        bare = {"shot_size": "wide", "camera_movement": "static", "image_prompt": "只有旧提示词"}
        from_llm = build_image_prompt(
            project_style="国漫", bible_style=None, characters=[], location=None, shot=bare
        )
        assert from_llm.core_source == "image_prompt"
        assert "只有旧提示词" in from_llm.prompt

        empty = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[],
            location=None,
            shot={"shot_size": "wide", "camera_movement": "static"},
        )
        assert empty.core_source == "none"

    def test_same_inputs_produce_byte_identical_prompts(self):
        first = build_image_prompt(
            project_style="国漫",
            bible_style="都市",
            characters=[CHARACTER],
            location=LOCATION,
            shot=SHOT,
        )
        second = build_image_prompt(
            project_style="国漫",
            bible_style="都市",
            characters=[CHARACTER],
            location=LOCATION,
            shot=SHOT,
        )
        assert first.prompt == second.prompt
        assert first.negative_prompt == second.negative_prompt

    def test_empty_layers_drop_their_whole_line(self):
        """A missing layer must not leave a dangling half-sentence behind."""
        built = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[],
            location=None,
            shot={"shot_size": "wide", "camera_movement": "", "visual_description": "空荡的教室"},
        )
        assert "运镜：" not in built.prompt
        assert ",，" not in built.prompt
        assert not built.prompt.endswith("，")
        # The style placeholder is substituted, and the file's section separator
        # never leaks into the prompt.
        assert "{style}" not in built.prompt
        assert "---" not in built.prompt

    def test_removing_a_layer_changes_the_output(self):
        """Guards against the builder ignoring an input it claims to use."""
        with_light = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[CHARACTER],
            location=LOCATION,
            shot=SHOT,
        )
        without_light = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[CHARACTER],
            location={**LOCATION, "lighting": ""},
            shot=SHOT,
        )
        assert with_light.prompt != without_light.prompt

    def test_reference_clause_only_appears_with_a_reference_image(self):
        plain = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[CHARACTER],
            location=LOCATION,
            shot=SHOT,
        )
        assert plain.layers["reference"] == ""

        referenced = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[{**CHARACTER, "reference_image_url": "http://x/ref.png"}],
            location=LOCATION,
            shot=SHOT,
        )
        assert referenced.layers["reference"] != ""
        assert "参考图" in referenced.prompt

    def test_negative_prompt_comes_from_the_prompt_file(self):
        built = build_image_prompt(
            project_style="国漫",
            bible_style=None,
            characters=[CHARACTER],
            location=LOCATION,
            shot=SHOT,
        )
        assert built.negative_prompt
        assert "文字" in built.negative_prompt

    def test_vocabulary_covers_every_prd_closed_set_value(self):
        """Adding an enum member must not silently drop it from prompts."""
        from app.models.enums import CameraMovement, ShotSize

        assert {value.value for value in ShotSize} <= set(SHOT_SIZE_PROMPT_LABELS)
        assert {value.value for value in CameraMovement} <= set(CAMERA_MOVEMENT_PROMPT_LABELS)


# ======================================================== mock provider bytes
class TestMockImageProvider:
    """The offline provider must produce usable, prompt-bound bytes."""

    async def test_produces_a_decodable_png(self):
        provider = MockImageProvider(max_pixels=10_000)
        result = await provider.generate(ImageRequest(prompt="测试提示词", width=200, height=120))
        assert result.data
        assert result.data.startswith(b"\x89PNG\r\n\x1a\n")
        assert decode_png_size(result.data) == (result.width, result.height)

    async def test_the_barcode_encodes_the_prompt_hash(self):
        """Proves a stored file really belongs to the prompt that made it."""
        from app.providers.image.mock import _BAR_BOTTOM, _BAR_HEIGHT, _BAR_LEFT, _BAR_WIDTH

        # Width must clear _BAR_LEFT + 32 * _BAR_WIDTH or the barcode is clipped,
        # and the pixel budget must not trigger downscaling (which would too).
        provider = MockImageProvider()
        result = await provider.generate(ImageRequest(prompt="镜头一", width=320, height=200))
        assert (result.width, result.height) == (320, 200)
        pixels = decode_png_pixels(result.data)

        bar_top = result.height - _BAR_BOTTOM - _BAR_HEIGHT
        row = pixels[bar_top + _BAR_HEIGHT // 2]
        decoded = [
            1 if row[_BAR_LEFT + i * _BAR_WIDTH + _BAR_WIDTH // 2][0] > 128 else 0
            for i in range(32)
        ]
        assert decoded == prompt_bits("镜头一")
        assert decoded != prompt_bits("镜头二")

    async def test_fail_times_raises_the_same_error_the_real_provider_would(self):
        provider = MockImageProvider(fail_times=2, max_pixels=5_000)
        for _ in range(2):
            with pytest.raises(ProviderError):
                await provider.generate(ImageRequest(prompt="x", width=80, height=50))
        # Third call succeeds: the budget is exhausted, not permanently broken.
        result = await provider.generate(ImageRequest(prompt="x", width=80, height=50))
        assert result.data


# ================================================== service: state machine
class TestImageServiceStateMachine:
    def test_queue_then_execute_reaches_success_with_an_asset(
        self, client: TestClient, token: str, storyboarded
    ):
        from app.core.database import SessionLocal
        from app.models.asset import Asset
        from app.models.shot import Shot

        project_id, _, shot_id = storyboarded
        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            project = shot.episode.project
            service = ImageService(db)
            task, reused = service.queue_shot_image(shot, project=project)
            assert reused is False
            assert task.status == TaskStatus.PENDING.value

            finished = service.execute_task(task.id)
            assert finished.status == TaskStatus.SUCCESS.value

            asset = db.query(Asset).filter(Asset.shot_id == shot.id).one()
            assert asset.storage_key.endswith(".png")
            assert asset.metadata_json["provider"] == "mock"
            assert asset.metadata_json["core_source"] == "visual_description"
            assert asset.metadata_json["layers"]["lighting"]
            # The shot points at the newest asset, and the bytes are on disk.
            db.refresh(shot)
            assert shot.image_asset_id == asset.id
        finally:
            db.close()

    def test_the_stored_file_is_a_real_png_keyed_by_the_prompt(
        self, client: TestClient, token: str, storyboarded
    ):
        from app.core.config import settings
        from app.core.database import SessionLocal
        from app.models.shot import Shot
        from app.storage import get_storage

        _, _, shot_id = storyboarded
        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            service = ImageService(db)
            task, _ = service.queue_shot_image(shot, project=shot.episode.project)
            service.execute_task(task.id)

            asset = service.assets.latest_for_shots([shot.id])[shot.id]
            raw = get_storage().read(asset.storage_key)
            assert raw.startswith(b"\x89PNG")
            # metadata width/height must describe the bytes actually written.
            assert decode_png_size(raw) == (
                asset.metadata_json["width"],
                asset.metadata_json["height"],
            )
            assert asset.metadata_json["bytes"] == len(raw)
            assert settings.storage_local_dir not in asset.url  # url is public, not a path
        finally:
            db.close()

    def test_idempotency_prevents_a_second_task_while_one_is_live(
        self, client: TestClient, token: str, storyboarded
    ):
        """PRD section 21: "必须保证幂等" -- a double-click must not double-charge."""
        from app.core.database import SessionLocal
        from app.models.shot import Shot

        _, _, shot_id = storyboarded
        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            service = ImageService(db)
            first, reused_first = service.queue_shot_image(shot, project=shot.episode.project)
            second, reused_second = service.queue_shot_image(shot, project=shot.episode.project)

            assert reused_first is False
            assert reused_second is True
            assert first.id == second.id
        finally:
            db.close()

    def test_an_asset_already_generated_is_refused_without_force(
        self, client: TestClient, token: str, storyboarded
    ):
        from app.core.database import SessionLocal
        from app.models.shot import Shot

        _, _, shot_id = storyboarded
        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            service = ImageService(db)
            task, _ = service.queue_shot_image(shot, project=shot.episode.project)
            service.execute_task(task.id)
            db.refresh(shot)

            with pytest.raises(ConflictError):
                service.queue_shot_image(shot, project=shot.episode.project)

            # force=True is the regenerate path and is allowed.
            forced, reused = service.queue_shot_image(
                shot, project=shot.episode.project, force=True
            )
            assert reused is False
            assert forced.id != task.id
        finally:
            db.close()

    def test_executing_a_finished_task_again_makes_no_new_asset(
        self, client: TestClient, token: str, storyboarded
    ):
        """Re-delivered queue messages must not pay for a second image."""
        from app.core.database import SessionLocal
        from app.models.asset import Asset
        from app.models.shot import Shot

        _, _, shot_id = storyboarded
        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            service = ImageService(db)
            task, _ = service.queue_shot_image(shot, project=shot.episode.project)
            service.execute_task(task.id)
            before = db.query(Asset).filter(Asset.shot_id == shot.id).count()

            service.execute_task(task.id)  # second delivery
            assert db.query(Asset).filter(Asset.shot_id == shot.id).count() == before
        finally:
            db.close()

    def test_retry_exhaustion_lands_on_failed_with_the_reason(
        self, client: TestClient, token: str, storyboarded, monkeypatch
    ):
        """RUNNING -> RETRY -> ... -> FAILED (PRD section 21) with a real reason."""
        from app.core.config import settings
        from app.core.database import SessionLocal
        from app.models.shot import Shot

        _, _, shot_id = storyboarded
        monkeypatch.setattr(settings, "celery_task_max_retries", 2)

        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            service = ImageService(db)
            # Always-failing provider: the retry budget is what is under test.
            service._provider = MockImageProvider(fail_times=99, max_pixels=5_000)
            task, _ = service.queue_shot_image(shot, project=shot.episode.project)

            finished = service.execute_task(task.id)
            assert finished.status == TaskStatus.FAILED.value
            assert finished.retry_count == 3  # initial attempt + 2 retries
            assert "故意失败" in (finished.error_message or "")
            db.refresh(shot)
            assert shot.status == "FAILED"
        finally:
            db.close()

    def test_a_failed_regeneration_does_not_blank_an_existing_image(
        self, client: TestClient, token: str, storyboarded, monkeypatch
    ):
        """Losing one attempt must not destroy the picture that already exists."""
        from app.core.config import settings
        from app.core.database import SessionLocal
        from app.models.enums import ShotStatus
        from app.models.shot import Shot

        _, _, shot_id = storyboarded
        monkeypatch.setattr(settings, "celery_task_max_retries", 0)

        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            service = ImageService(db)
            task, _ = service.queue_shot_image(shot, project=shot.episode.project)
            service.execute_task(task.id)
            db.refresh(shot)
            assert shot.image_asset_id is not None

            service._provider = MockImageProvider(fail_times=99, max_pixels=5_000)
            retry_task, _ = service.queue_shot_image(shot, project=shot.episode.project, force=True)
            service.execute_task(retry_task.id)

            db.refresh(shot)
            assert shot.status == ShotStatus.COMPLETED.value  # not FAILED
            assert shot.image_asset_id is not None
        finally:
            db.close()

    def test_execute_of_an_unknown_task_is_404(self, client: TestClient):
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            with pytest.raises(NotFoundError):
                ImageService(db).execute_task(uuid.uuid4())
        finally:
            db.close()

    def test_character_reference_reaches_the_characters_own_column(
        self, client: TestClient, token: str, storyboarded
    ):
        from app.core.database import SessionLocal
        from app.models.character import Character

        project_id, _, _ = storyboarded
        db = SessionLocal()
        try:
            character = (
                db.query(Character).filter(Character.project_id == uuid.UUID(project_id)).first()
            )
            assert character is not None
            service = ImageService(db)
            task, _ = service.queue_character_reference(
                character, project=character.project, force=True
            )
            service.execute_task(task.id)

            db.refresh(character)
            assert character.reference_image_url
            assert "expires=" in character.reference_image_url
            # A reference sheet is a CHARACTER asset, not attached to a shot.
            asset = service.assets.list_for_project(uuid.UUID(project_id))[0]
            assert asset.shot_id is None
            assert asset.metadata_json["character_id"] == str(character.id)
        finally:
            db.close()


# ============================================================ signing (PRD 27)
class TestSignedUrls:
    def test_a_signed_url_verifies_and_a_tampered_one_does_not(self):
        url = sign_storage_url("project/a/shots/b.png", ttl_seconds=60)
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        assert verify_storage_signature("project/a/shots/b.png", query["expires"], query["sig"])
        assert not verify_storage_signature(
            "project/a/shots/OTHER.png", query["expires"], query["sig"]
        )

    def test_an_expired_signature_is_refused(self):
        import time

        url = sign_storage_url("project/a/shots/b.png", ttl_seconds=-10)
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        assert not verify_storage_signature("project/a/shots/b.png", query["expires"], query["sig"])
        assert int(query["expires"]) < int(time.time())


# ================================================================== HTTP
class TestImageApi:
    def test_generate_returns_a_task_and_produces_the_image(
        self, client: TestClient, token: str, storyboarded
    ):
        _, episode_id, shot_id = storyboarded
        response = client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))
        assert response.status_code == 201, response.text
        data = _data(response)
        assert data["reused"] is False
        assert data["task"]["task_type"] == "IMAGE"

        # Eager Celery: the task ran inline, so the storyboard now carries the image.
        storyboard = _data(
            client.get(f"/api/v1/episodes/{episode_id}/storyboard", headers=_headers(token))
        )
        media = storyboard["media"][shot_id]
        assert media["image_count"] == 1
        assert media["asset"]["type"] == "IMAGE"
        assert media["asset"]["url"].startswith("http")

    def test_downloading_the_signed_url_returns_the_png_bytes(
        self, client: TestClient, token: str, storyboarded
    ):
        """The URL handed to the UI must actually serve the file (PRD section 27)."""
        _, _, shot_id = storyboarded
        client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))
        task_id = _data(
            client.get(f"/api/v1/projects/{storyboarded[0]}/tasks", headers=_headers(token))
        )["items"][0]["id"]
        asset = _data(client.get(f"/api/v1/tasks/{task_id}", headers=_headers(token)))["asset"]

        path = asset["url"].split("http://testserver", 1)[1]
        file_response = client.get(path)
        assert file_response.status_code == 200, file_response.text
        assert file_response.content.startswith(b"\x89PNG")

        # Same path without a valid signature must not serve the file.
        assert client.get(path.split("?")[0]).status_code == 403

    def test_second_generate_without_force_is_a_conflict(
        self, client: TestClient, token: str, storyboarded
    ):
        _, _, shot_id = storyboarded
        client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))
        response = client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))
        assert response.status_code == 409
        assert _error_code(response) == "CONFLICT"

    def test_regenerate_keeps_the_previous_asset_on_disk(
        self, client: TestClient, token: str, storyboarded
    ):
        _, episode_id, shot_id = storyboarded
        client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))
        response = client.post(f"/api/v1/shots/{shot_id}/regenerate", headers=_headers(token))
        assert response.status_code == 201, response.text

        storyboard = _data(
            client.get(f"/api/v1/episodes/{episode_id}/storyboard", headers=_headers(token))
        )
        # Two attempts, two assets; the newest one is the shot's current picture.
        assert storyboard["media"][shot_id]["image_count"] == 2

    def test_regenerate_for_video_is_refused_not_silently_an_image(
        self, client: TestClient, token: str, storyboarded
    ):
        _, _, shot_id = storyboarded
        response = client.post(
            f"/api/v1/shots/{shot_id}/regenerate",
            headers=_headers(token),
            params={"kind": "video"},
        )
        assert response.status_code >= 400
        assert _error_code(response) == "UNSUPPORTED"

    def test_batch_fill_skips_shots_that_already_have_a_picture(
        self, client: TestClient, token: str, storyboarded
    ):
        _, episode_id, shot_id = storyboarded
        client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))

        data = _data(
            client.post(f"/api/v1/episodes/{episode_id}/images/generate", headers=_headers(token))
        )
        assert data["skipped_existing"] == 1
        assert data["queued"] == data["shots_total"] - 1

        storyboard = _data(
            client.get(f"/api/v1/episodes/{episode_id}/storyboard", headers=_headers(token))
        )
        assert all(entry["image_count"] == 1 for entry in storyboard["media"].values())

    def test_task_list_reports_status_totals(self, client: TestClient, token: str, storyboarded):
        project_id, _, shot_id = storyboarded
        client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))
        data = _data(client.get(f"/api/v1/projects/{project_id}/tasks", headers=_headers(token)))
        assert data["totals"]["tasks"] == 1
        assert data["totals"]["by_status"]["SUCCESS"] == 1

    def test_retry_of_a_successful_task_is_a_conflict(
        self, client: TestClient, token: str, storyboarded
    ):
        project_id, _, shot_id = storyboarded
        client.post(f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(token))
        task_id = _data(
            client.get(f"/api/v1/projects/{project_id}/tasks", headers=_headers(token))
        )["items"][0]["id"]

        response = client.post(f"/api/v1/tasks/{task_id}/retry", headers=_headers(token))
        assert response.status_code == 409

    def test_retry_of_a_failed_task_requeues_and_succeeds(
        self, client: TestClient, token: str, storyboarded, monkeypatch
    ):
        """The one path where a retry endpoint earns its existence."""
        from app.core.database import SessionLocal
        from app.models.generation_task import GenerationTask
        from app.models.shot import Shot

        project_id, _, shot_id = storyboarded
        # Fail the first attempt permanently (retry budget 0), then let the retry win.
        db = SessionLocal()
        try:
            shot = db.get(Shot, uuid.UUID(shot_id))
            service = ImageService(db)
            service._provider = MockImageProvider(fail_times=1, max_pixels=5_000)
            from app.core.config import settings

            monkeypatch.setattr(settings, "celery_task_max_retries", 0)
            task, _ = service.queue_shot_image(shot, project=shot.episode.project)
            assert service.execute_task(task.id).status == TaskStatus.FAILED.value
        finally:
            db.close()

        task_id = _data(
            client.get(f"/api/v1/projects/{project_id}/tasks", headers=_headers(token))
        )["items"][0]["id"]

        response = client.post(f"/api/v1/tasks/{task_id}/retry", headers=_headers(token))
        assert response.status_code == 201, response.text
        # The response is a pre-execution snapshot (PENDING) -- correct for the
        # async contract, and identical whether a worker or eager mode runs it.
        assert _data(response)["task"]["status"] == TaskStatus.PENDING.value

        db = SessionLocal()
        try:
            row = db.get(GenerationTask, uuid.UUID(task_id))
            assert row.status == TaskStatus.SUCCESS.value
            assert row.retry_count == 0  # fresh budget
        finally:
            db.close()

    def test_reference_endpoints_are_reachable(self, client: TestClient, token: str, storyboarded):
        project_id, _, _ = storyboarded
        bible = _data(client.get(f"/api/v1/projects/{project_id}/bible", headers=_headers(token)))
        character_id = bible["characters"][0]["id"]
        location_id = bible["locations"][0]["id"]

        character_response = client.post(
            f"/api/v1/characters/{character_id}/reference/generate",
            headers=_headers(token),
            params={"force": True},
        )
        assert character_response.status_code == 201, character_response.text

        location_response = client.post(
            f"/api/v1/locations/{location_id}/reference/generate",
            headers=_headers(token),
            params={"force": True},
        )
        assert location_response.status_code == 201, location_response.text

        refreshed = _data(
            client.get(f"/api/v1/projects/{project_id}/bible", headers=_headers(token))
        )
        by_id = {item["id"]: item for item in refreshed["characters"]}
        assert by_id[character_id]["reference_image_url"]
        assert {item["id"]: item for item in refreshed["locations"]}[location_id][
            "reference_image_url"
        ]

    def test_generate_for_a_shot_owned_by_someone_else_is_404(
        self, client: TestClient, token: str, other_token: str, storyboarded
    ):
        _, _, shot_id = storyboarded
        response = client.post(
            f"/api/v1/shots/{shot_id}/image/generate", headers=_headers(other_token)
        )
        assert response.status_code == 404
        assert _error_code(response) == "NOT_FOUND"

    def test_tasks_of_another_users_project_are_not_listed(
        self, client: TestClient, token: str, other_token: str, storyboarded
    ):
        project_id, _, _ = storyboarded
        response = client.get(f"/api/v1/projects/{project_id}/tasks", headers=_headers(other_token))
        assert response.status_code == 404

    def test_unknown_shot_and_task_are_404(self, client: TestClient, token: str):
        missing = uuid.uuid4()
        shot_response = client.post(
            f"/api/v1/shots/{missing}/image/generate", headers=_headers(token)
        )
        assert shot_response.status_code == 404
        assert client.get(f"/api/v1/tasks/{missing}", headers=_headers(token)).status_code == 404

    def test_unauthenticated_requests_are_401(self, client: TestClient, storyboarded):
        _, _, shot_id = storyboarded
        assert client.post(f"/api/v1/shots/{shot_id}/image/generate").status_code == 401

    def test_error_envelope_shape(self, client: TestClient, token: str):
        response = client.get(f"/api/v1/tasks/{uuid.uuid4()}", headers=_headers(token))
        body = response.json()
        assert body["success"] is False
        assert body["data"] is None
        assert set(body["error"]) >= {"code", "message"}
        assert body["request_id"]


class TestProjectAssets:
    """GET /projects/{id}/assets backs the project's 素材 page (PRD 5.3).

    Section 22 routes no way to read assets back, so the only previous path was the
    per-shot media inside a storyboard response -- fine for rendering a board,
    useless for a gallery. These lock down that a gallery can be built from one
    request, with the labels it needs already attached.
    """

    def test_assets_are_listed_with_labels(self, client: TestClient, token: str, storyboarded):
        project_id, episode_id, _ = storyboarded
        _data(
            client.post(f"/api/v1/episodes/{episode_id}/images/generate", headers=_headers(token))
        )
        # This endpoint returns a bare list (episodes.py: ok([...])), not an envelope
        # with "items" -- unlike the paginated project list.
        shots = _data(client.get(f"/api/v1/episodes/{episode_id}/shots", headers=_headers(token)))

        payload = _data(
            client.get(f"/api/v1/projects/{project_id}/assets", headers=_headers(token))
        )
        assert payload["totals"]["assets"] >= len(shots), payload["totals"]
        assert payload["totals"]["by_type"]["IMAGE"] == payload["totals"]["assets"]

        by_shot = {item["shot_id"]: item for item in payload["items"] if item["shot_id"]}
        assert len(by_shot) == len(shots), "每个镜头都应有素材"

        sample = by_shot[shots[0]["id"]]
        # The grid labels each tile from these, so they must be present, not null.
        assert sample["shot_number"] >= 1
        assert sample["scene_id"]
        assert sample["type"] == "IMAGE"
        assert sample["url"] and "expires=" in sample["url"], "素材 URL 必须是新鲜签名"

    def test_assets_are_scoped_to_their_owner(
        self, client: TestClient, storyboarded, other_token: str
    ):
        project_id, _, _ = storyboarded
        response = client.get(
            f"/api/v1/projects/{project_id}/assets", headers=_headers(other_token)
        )
        assert response.status_code == 404, response.text

    def test_assets_can_be_filtered_by_type(self, client: TestClient, token: str, storyboarded):
        project_id, episode_id, _ = storyboarded
        client.post(f"/api/v1/episodes/{episode_id}/images/generate", headers=_headers(token))

        payload = _data(
            client.get(
                f"/api/v1/projects/{project_id}/assets",
                headers=_headers(token),
                params={"asset_type": "VIDEO"},
            )
        )
        # Phase 5 produces images only; Phase 6 adds video. Filtering must not error.
        assert payload["totals"]["assets"] == 0
        assert payload["items"] == []
