"""Image generation service (PRD Phase 5: ImageProvider, Reference, Image Task).

Owns the whole PRD section 21 contract:

    POST /generate -> create generation_task -> queue -> worker -> Provider
                   -> save Asset -> update Task

Split in two halves on purpose:

* ``queue_*`` runs in the request: it validates, enforces idempotency, writes the
  ``PENDING`` row and hands it to the queue. It is cheap -- no provider call, no
  file write -- so the HTTP request returns immediately (PRD section 30 principle
  4: "长任务异步化", a slow provider must never block a request).
* ``execute_task`` runs in the worker: it builds the prompt, calls the provider,
  stores the bytes, writes the ``Asset`` and moves the state machine forward. It
  retries in-process (see below) so the behaviour is identical with a real Celery
  worker and with ``CELERY_TASK_ALWAYS_EAGER=true`` -- otherwise the retry path
  would only ever be exercised in one of the two, which is how retry bugs hide.

Retry is a loop here rather than Celery's ``self.retry``: Celery retries re-queue
the message, which eager mode does not do at all, so the DB-visible state machine
(PRD section 21's ``RUNNING -> FAILED -> RETRY``) would differ by transport.

Idempotency is enforced twice, deliberately: an in-flight task is reused instead
of duplicated (that is the ``idempotency_key`` partial unique index), and a task
that already reached ``SUCCESS`` is never re-executed -- so a re-delivered message
cannot pay for a second image or overwrite a good file with a bad one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ProviderError, ValidationError
from app.core.signing import sign_storage_url
from app.models.character import Character
from app.models.enums import AssetType, ShotStatus, TaskStatus, TaskType
from app.models.episode import Episode
from app.models.generation_task import GenerationTask
from app.models.location import Location
from app.models.project import Project
from app.models.shot import Shot
from app.providers.base import ImageProvider, ImageRequest
from app.providers.image.factory import get_image_provider
from app.repositories.media import AssetRepository, GenerationTaskRepository
from app.schemas.media import AssetOut, TaskOut
from app.services.prompt_builder import build_image_prompt, build_reference_prompt
from app.storage import StorageBackend, get_storage
from app.utils.async_ import run_async

# Where a task's payload says what it is generating. PRD section 17's task_type
# vocabulary has no separate "reference" member, so reference work is an IMAGE
# task whose payload names its target -- the vocabulary stays as specified.
TARGET_SHOT = "shot"
TARGET_CHARACTER = "character"
TARGET_LOCATION = "location"


def asset_to_dict(asset) -> dict | None:
    """Serialise an asset with a freshly signed URL (PRD section 27).

    Shared by the media routes and by the storyboard response so there is exactly
    one place that decides what an asset looks like on the wire.
    """
    if asset is None:
        return None
    payload = AssetOut.model_validate(asset)
    payload.url = sign_storage_url(asset.storage_key, ttl_seconds=settings.asset_url_ttl_seconds)
    return payload.model_dump(mode="json")


def task_to_dict(task) -> dict:
    payload = TaskOut.model_validate(task)
    payload.max_retries = settings.celery_task_max_retries
    return payload.model_dump(mode="json")


def _now() -> datetime:
    return datetime.now(UTC)


def _error_text(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    # Keep the column readable; the full traceback is in the worker log.
    return text[:2000]


class ImageService:
    def __init__(
        self,
        db: Session,
        *,
        provider: ImageProvider | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        self.db = db
        # Injected in tests; resolved lazily otherwise so importing the service
        # does not require a configured provider/storage root.
        self._provider = provider
        self._storage = storage
        self.assets = AssetRepository(db)
        self.tasks = GenerationTaskRepository(db)

    @property
    def provider(self) -> ImageProvider:
        if self._provider is None:
            self._provider = get_image_provider()
        return self._provider

    @property
    def storage(self) -> StorageBackend:
        if self._storage is None:
            self._storage = get_storage()
        return self._storage

    # ================================================================== queueing
    def queue_shot_image(
        self, shot: Shot, *, project: Project, force: bool = False
    ) -> tuple[GenerationTask, bool]:
        """Queue an image for one shot. Returns ``(task, reused_existing)``.

        With ``force=False`` an existing picture is a conflict rather than a silent
        overwrite -- the same guard shape as the story analysis and episode plan
        endpoints, so re-generating is always an explicit choice.
        """
        key = f"shot-image:{shot.id}"
        live = self.tasks.find_live_by_key(key)
        if live is not None:
            return live, True
        if shot.image_asset_id is not None and not force:
            raise ConflictError("该镜头已有图片，如需重新生成请使用 regenerate（会保留旧图）")

        task = self.tasks.create(
            project_id=project.id,
            episode_id=shot.episode_id,
            shot_id=shot.id,
            task_type=TaskType.IMAGE.value,
            status=TaskStatus.PENDING.value,
            provider=self.provider.name,
            model=self.provider.model,
            idempotency_key=key,
            input_payload={
                "target": TARGET_SHOT,
                "shot_id": str(shot.id),
                "shot_number": shot.shot_number,
                "scene_id": shot.scene_id,
            },
        )
        self.db.commit()
        return task, False

    def queue_character_reference(
        self, character: Character, *, project: Project, force: bool = False
    ) -> tuple[GenerationTask, bool]:
        key = f"character-reference:{character.id}"
        live = self.tasks.find_live_by_key(key)
        if live is not None:
            return live, True
        if character.reference_image_url and not force:
            raise ConflictError("该人物已有参考图，如需重新生成请使用 regenerate")

        task = self.tasks.create(
            project_id=project.id,
            task_type=TaskType.IMAGE.value,
            status=TaskStatus.PENDING.value,
            provider=self.provider.name,
            model=self.provider.model,
            idempotency_key=key,
            input_payload={
                "target": TARGET_CHARACTER,
                "character_id": str(character.id),
                "name": character.name,
            },
        )
        self.db.commit()
        return task, False

    def queue_location_reference(
        self, location: Location, *, project: Project, force: bool = False
    ) -> tuple[GenerationTask, bool]:
        key = f"location-reference:{location.id}"
        live = self.tasks.find_live_by_key(key)
        if live is not None:
            return live, True
        if location.reference_image_url and not force:
            raise ConflictError("该场景已有参考图，如需重新生成请使用 regenerate")

        task = self.tasks.create(
            project_id=project.id,
            task_type=TaskType.IMAGE.value,
            status=TaskStatus.PENDING.value,
            provider=self.provider.name,
            model=self.provider.model,
            idempotency_key=key,
            input_payload={
                "target": TARGET_LOCATION,
                "location_id": str(location.id),
                "name": location.name,
            },
        )
        self.db.commit()
        return task, False

    # =========================================================== reporting
    def shot_media_map(self, shots: list[Shot]) -> dict[str, dict]:
        """Per-shot media state for a storyboard response, in three queries.

        Returned keyed by shot id as a string (JSON object keys) so the client can
        look a shot up without a second request.
        """
        shot_ids = [shot.id for shot in shots]
        assets = self.assets.latest_for_shots(shot_ids)
        counts = self.assets.image_counts_for_shots(shot_ids)
        latest_task_ids = self.tasks.latest_task_ids_for_shots(shot_ids)

        result: dict[str, dict] = {}
        for shot in shots:
            task = None
            task_id = latest_task_ids.get(shot.id)
            if task_id is not None:
                task = self.tasks.get(task_id)
            result[str(shot.id)] = {
                "shot_id": str(shot.id),
                "shot_number": shot.shot_number,
                "scene_id": shot.scene_id,
                "status": shot.status,
                "image_asset_id": str(shot.image_asset_id) if shot.image_asset_id else None,
                "asset": asset_to_dict(assets.get(shot.id)),
                "image_count": counts.get(shot.id, 0),
                "latest_task": task_to_dict(task) if task is not None else None,
            }
        return result

    def episode_image_status(self, episode) -> dict:
        """Rollup for one episode: how many shots have pictures, task states."""
        shots = (
            self.db.execute(
                select(Shot).where(Shot.episode_id == episode.id).order_by(Shot.sequence)
            )
            .scalars()
            .all()
        )
        counts = self.assets.image_counts_for_shots([shot.id for shot in shots])
        with_image = sum(1 for shot in shots if counts.get(shot.id))

        tasks = [
            task
            for task in self.tasks.list_for_project(episode.project_id, limit=500)
            if task.task_type == TaskType.IMAGE.value
        ]
        by_status = {state.value: 0 for state in TaskStatus}
        for task in tasks:
            by_status[task.status] = by_status.get(task.status, 0) + 1

        return {
            "episode_id": str(episode.id),
            "shots_total": len(shots),
            "shots_with_image": with_image,
            "tasks_pending": by_status.get(TaskStatus.PENDING.value, 0),
            "tasks_running": by_status.get(TaskStatus.RUNNING.value, 0)
            + by_status.get(TaskStatus.RETRY.value, 0),
            "tasks_failed": by_status.get(TaskStatus.FAILED.value, 0),
            "provider": self.provider.name,
            "model": self.provider.model,
        }

    # ================================================================ execution
    def execute_task(self, task_id: uuid.UUID) -> GenerationTask:
        """Run a task to completion (or to FAILED). Safe to call twice."""
        task = self.tasks.get(task_id)
        if task is None:
            raise NotFoundError("生成任务不存在")

        # A task that already produced an asset must not run again: re-delivery
        # (Celery at-least-once) or an impatient retry button would otherwise
        # spend money again and could replace a good image with a worse one.
        if task.status == TaskStatus.SUCCESS.value:
            return task

        max_attempts = 1 + max(0, settings.celery_task_max_retries)
        while task.retry_count < max_attempts:
            task.status = TaskStatus.RUNNING.value
            task.started_at = _now()
            self.db.commit()

            try:
                self._run_once(task)
            except Exception as exc:  # noqa: BLE001 -- recorded, then retried
                task.retry_count += 1
                task.error_message = _error_text(exc)
                exhausted = task.retry_count >= max_attempts
                task.status = TaskStatus.FAILED.value if exhausted else TaskStatus.RETRY.value
                if exhausted:
                    task.completed_at = _now()
                    self._mark_target_failed(task)
                self.db.commit()
                if exhausted:
                    return task
            else:
                task.status = TaskStatus.SUCCESS.value
                task.completed_at = _now()
                task.error_message = None
                self.db.commit()
                return task

        return task

    def _run_once(self, task: GenerationTask) -> None:
        payload = task.input_payload or {}
        target = str(payload.get("target") or "")

        if target == TARGET_CHARACTER:
            self._run_character_reference(task, uuid.UUID(str(payload["character_id"])))
        elif target == TARGET_LOCATION:
            self._run_location_reference(task, uuid.UUID(str(payload["location_id"])))
        else:
            self._run_shot_image(task)

    # ------------------------------------------------------------ shot image
    def _run_shot_image(self, task: GenerationTask) -> None:
        if task.shot_id is None:
            raise ValidationError("图片任务缺少 shot_id")
        shot = self.db.get(Shot, task.shot_id)
        if shot is None:
            raise NotFoundError("镜头不存在")

        project = self.db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在")

        characters, location = self._shot_context(shot)
        built = build_image_prompt(
            project_style=project.style,
            bible_style=self._bible_style(project),
            characters=characters,
            location=location,
            shot={
                "shot_size": shot.shot_size,
                "camera_movement": shot.camera_movement,
                "expression": shot.expression,
                "action": shot.action,
                "visual_description": shot.visual_description,
                "image_prompt": shot.image_prompt,
            },
        )

        asset = self._generate_and_store(
            task,
            prompt=built.prompt,
            negative_prompt=built.negative_prompt,
            storage_key=self._storage_key(project.id, "shots", shot.id),
            extra_metadata={
                "prompt_version": built.prompt_version,
                "core_source": built.core_source,
                "layers": built.layers,
                "scene_id": shot.scene_id,
                "shot_number": shot.shot_number,
            },
        )

        shot.image_asset_id = asset.id
        shot.status = ShotStatus.COMPLETED.value
        task.output_payload = {
            "asset_id": str(asset.id),
            "storage_key": asset.storage_key,
            "type": AssetType.IMAGE.value,
        }

    # -------------------------------------------------------- reference images
    def _run_character_reference(self, task: GenerationTask, character_id: uuid.UUID) -> None:
        character = self.db.get(Character, character_id)
        if character is None:
            raise NotFoundError("人物不存在")
        project = self.db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在")

        built = build_reference_prompt(
            project_style=project.style,
            bible_style=self._bible_style(project),
            kind="角色",
            name=character.name,
            detail=self._join_parts([character.appearance, character.hair, character.clothing]),
        )
        asset = self._generate_and_store(
            task,
            prompt=built.prompt,
            negative_prompt=built.negative_prompt,
            storage_key=self._storage_key(project.id, "characters", character.id),
            extra_metadata={
                "prompt_version": built.prompt_version,
                "character_id": str(character.id),
                "name": character.name,
            },
        )
        # A signed URL, not a durable value -- hence CharacterOut re-signs it on
        # every read (app/schemas/bible.py). Storing it keeps the PRD section 17
        # column shape without letting the hour-long expiry rot the row.
        character.reference_image_url = asset.url

    def _run_location_reference(self, task: GenerationTask, location_id: uuid.UUID) -> None:
        location = self.db.get(Location, location_id)
        if location is None:
            raise NotFoundError("场景不存在")
        project = self.db.get(Project, task.project_id)
        if project is None:
            raise NotFoundError("项目不存在")

        built = build_reference_prompt(
            project_style=project.style,
            bible_style=self._bible_style(project),
            kind="场景",
            name=location.name,
            detail=self._join_parts([location.description, location.lighting]),
            palette=location.visual_style,
        )
        asset = self._generate_and_store(
            task,
            prompt=built.prompt,
            negative_prompt=built.negative_prompt,
            storage_key=self._storage_key(project.id, "locations", location.id),
            extra_metadata={
                "prompt_version": built.prompt_version,
                "location_id": str(location.id),
                "name": location.name,
            },
        )
        # See _run_character_reference: re-signed on read.
        location.reference_image_url = asset.url

    # -------------------------------------------------------------------- steps
    def _generate_and_store(
        self,
        task: GenerationTask,
        *,
        prompt: str,
        negative_prompt: str | None,
        storage_key: str,
        extra_metadata: dict[str, Any],
    ):
        """Call the provider, persist the bytes, write the ``Asset`` row."""
        request = ImageRequest(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=settings.image_width,
            height=settings.image_height,
            prompt_version=extra_metadata.get("prompt_version"),
        )
        result = run_async(self.provider.generate(request))

        data = result.data
        if not data:
            # A vendor that only returns a URL is a provider bug for our storage
            # model: we must own the bytes (PRD section 25).
            raise ProviderError("图像 Provider 未返回字节数据，无法归档为 Asset")

        saved_key = self.storage.save(storage_key, data, content_type="image/png")
        # Recomputed rather than stored-and-forgotten: a signed URL expires, so
        # the value handed to clients is always fresh (see app/core/signing.py).
        url = sign_storage_url(saved_key, ttl_seconds=settings.asset_url_ttl_seconds)

        metadata = {
            **extra_metadata,
            "provider_metadata": result.metadata,
            "provider": task.provider,
            "model": task.model,
            "width": result.width,
            "height": result.height,
            "bytes": len(data),
            "content_type": "image/png",
        }
        return self.assets.create(
            project_id=task.project_id,
            episode_id=task.episode_id,
            shot_id=task.shot_id,
            type=AssetType.IMAGE.value,
            storage_key=saved_key,
            url=url,
            metadata_json=metadata,
        )

    def _mark_target_failed(self, task: GenerationTask) -> None:
        """Reflect a permanent failure on the target, without destroying output."""
        payload = task.input_payload or {}
        if str(payload.get("target") or "") == TARGET_SHOT and task.shot_id is not None:
            shot = self.db.get(Shot, task.shot_id)
            if shot is not None:
                # A failed regeneration must not blank an existing picture.
                shot.status = (
                    ShotStatus.COMPLETED.value
                    if shot.image_asset_id is not None
                    else ShotStatus.FAILED.value
                )

    # ------------------------------------------------------------------ helpers
    def _shot_context(self, shot: Shot) -> tuple[list[dict], dict | None]:
        """The characters in this shot and its scene's location, as dicts.

        Read through the episode's script JSON: the shot stores character *names*,
        and the scene->location binding lives in the script, so both require a
        lookup rather than a column on the shot.
        """
        episode = self.db.get(Episode, shot.episode_id)
        if episode is None:
            raise NotFoundError("剧集不存在")

        names = list(shot.characters_json or [])
        characters: list[dict] = []
        if names:
            statement = select(Character).where(
                Character.project_id == episode.project_id,
                Character.name.in_(names),
            )
            rows = self.db.execute(statement).scalars().all()
            characters = [
                {
                    "name": row.name,
                    "appearance": row.appearance,
                    "hair": row.hair,
                    "clothing": row.clothing,
                    "reference_image_url": row.reference_image_url,
                }
                for row in rows
            ]

        location: dict | None = None
        location_id = self._scene_location_id(episode, shot.scene_id)
        if location_id:
            row = self.db.get(Location, location_id)
            if row is not None:
                location = {
                    "name": row.name,
                    "description": row.description,
                    "lighting": row.lighting,
                    "visual_style": row.visual_style,
                    "reference_image_url": row.reference_image_url,
                }
        return characters, location

    @staticmethod
    def _scene_location_id(episode, scene_id: str) -> uuid.UUID | None:
        scenes = ((episode.script_json or {}).get("scenes")) or []
        for scene in scenes:
            if isinstance(scene, dict) and str(scene.get("scene_id")) == str(scene_id):
                try:
                    return uuid.UUID(str(scene.get("location_id")))
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _bible_style(project: Project) -> str | None:
        # ``_meta`` is provenance, not story data -- never treat it as content.
        bible = {
            key: value
            for key, value in (project.story_bible_json or {}).items()
            if not key.startswith("_")
        }
        style = bible.get("style")
        return str(style) if style else None

    @staticmethod
    def _storage_key(project_id: uuid.UUID, folder: str, entity_id: uuid.UUID) -> str:
        """PRD section 25's layout: ``project/<id>/<folder>/<name>``."""
        return f"project/{project_id}/{folder}/{entity_id}.png"

    @staticmethod
    def _join_parts(parts: list[str | None]) -> str:
        return "，".join(str(p).strip() for p in parts if p and str(p).strip())


__all__ = [
    "TARGET_CHARACTER",
    "TARGET_LOCATION",
    "TARGET_SHOT",
    "ImageService",
]
