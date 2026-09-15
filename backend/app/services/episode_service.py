"""Episode Agent orchestration + persistence (PRD sections 9, 10, 11, 19, 38).

Three entry points, matching PRD section 22's API shape:

* :meth:`EpisodeService.plan`         -- story -> episode outline (replaces the plan)
* :meth:`EpisodeService.generate_script`     -- one episode -> script
* :meth:`EpisodeService.generate_storyboard` -- script -> shots + consistency report

Two invariants worth stating explicitly, because both were choices:

1. **Rosters come from the database, not from workflow state.** The script must
   bind to real ``character_id``/``location_id`` values (PRD section 10), and ids
   only exist once the Bible has been persisted -- the agent's own node output
   carries none. So every generate call loads the Bibles from their tables.
2. **Shots are deleted and recreated, unlike characters/locations.** A
   storyboard is a single ordered artefact whose rows have no independent
   identity or user hand-edits to preserve at this stage (Phases 5-7 attach media
   by ``shot.id``, which is why re-generating invalidates them). Upserting by
   ``(scene_id, shot_number)`` was rejected: a shot's *content* changes wholesale
   when the script changes, so matching old rows would attach old media to new
   content. Documented in docs/TDD.md section 18.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents.consistency import check_script_bindings, check_storyboard
from app.agents.episode_graph import (
    run_episode_planner,
    run_script_generator,
    run_storyboard_generator,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.enums import EpisodeStatus, GenerationStatus
from app.models.episode import Episode
from app.models.project import Project
from app.providers.base import LLMProvider
from app.providers.llm.factory import get_llm_provider
from app.repositories.character import CharacterRepository
from app.repositories.episode import EpisodeRepository, ShotRepository
from app.repositories.location import LocationRepository
from app.repositories.project import ProjectRepository
from app.schemas.episode import (
    ConsistencyReport,
    EpisodeCreate,
    EpisodeOut,
    EpisodeUpdate,
    ScriptContent,
    ScriptUpdate,
    StoryboardContent,
    StoryboardUpdate,
)

logger = logging.getLogger(__name__)

MIN_EPISODES = 1
MAX_EPISODES = 24
DEFAULT_EPISODE_COUNT = 6

# Mirrors the analyze guard: a project with no Bible cannot produce a script
# because there is nothing to bind ids to.
SCRIPT_REQUIRED_ANALYSIS = "SUCCEEDED"


class EpisodeService:
    """Plan episodes, generate scripts and storyboards, persist shots."""

    def __init__(self, db: Session, *, provider: LLMProvider | None = None) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.episodes = EpisodeRepository(db)
        self.shots = ShotRepository(db)
        self.characters = CharacterRepository(db)
        self.locations = LocationRepository(db)
        self._provider = provider

    @property
    def provider(self) -> LLMProvider:
        """Resolved lazily so settings are read per-process, not per-import."""
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    # ------------------------------------------------------------------- reads
    def list(self, project: Project) -> list[EpisodeOut]:
        rows = self.episodes.list_for_project(project.id)
        counts = self.episodes.shot_counts([row.id for row in rows])
        return [self._to_out(row, shot_count=counts.get(row.id, 0)) for row in rows]

    def get_model(self, user_id: uuid.UUID, episode_id: uuid.UUID) -> Episode:
        episode = self.episodes.get_for_user(episode_id, user_id)
        if episode is None:
            raise NotFoundError("剧集不存在")
        return episode

    def get_out(self, user_id: uuid.UUID, episode_id: uuid.UUID) -> EpisodeOut:
        episode = self.get_model(user_id, episode_id)
        return self._to_out(episode, shot_count=self.shots.count_for_episode(episode.id))

    def get_project_for_episode(self, episode: Episode) -> Project:
        project = self.projects.get(episode.project_id)
        if project is None:  # pragma: no cover -- FK guarantees it
            raise NotFoundError("项目不存在")
        return project

    # ------------------------------------------------------------------ episode CRUD
    def create(self, project: Project, payload: EpisodeCreate) -> EpisodeOut:
        number = payload.episode_number or self.episodes.next_episode_number(project.id)
        if number > MAX_EPISODES:
            raise ValidationError(f"每部作品最多 {MAX_EPISODES} 集")

        if self.episodes.get_by_number(project.id, number) is not None:
            raise ConflictError(f"第 {number} 集已存在")

        episode = self.episodes.create(
            project_id=project.id,
            episode_number=number,
            title=payload.title,
            summary=payload.summary,
            duration=payload.duration,
        )
        self.db.commit()
        self.db.refresh(episode)
        logger.info("episode %s created for project %s", number, project.id)
        return self._to_out(episode, shot_count=0)

    def update(
        self, user_id: uuid.UUID, episode_id: uuid.UUID, payload: EpisodeUpdate
    ) -> EpisodeOut:
        episode = self.get_model(user_id, episode_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationError("没有需要更新的字段")

        new_number = changes.get("episode_number")
        if new_number is not None and new_number != episode.episode_number:
            if new_number > MAX_EPISODES:
                raise ValidationError(f"每部作品最多 {MAX_EPISODES} 集")
            clash = self.episodes.get_by_number(episode.project_id, new_number)
            if clash is not None and clash.id != episode.id:
                raise ConflictError(f"第 {new_number} 集已存在")

        for field, value in changes.items():
            if field == "status" and value is not None:
                value = value.value if hasattr(value, "value") else value
            setattr(episode, field, value)

        self.db.commit()
        self.db.refresh(episode)
        return self._to_out(episode, shot_count=self.shots.count_for_episode(episode.id))

    def delete(self, user_id: uuid.UUID, episode_id: uuid.UUID) -> None:
        episode = self.get_model(user_id, episode_id)
        self.episodes.delete(episode)
        self.db.commit()

    def delete_all(self, project: Project) -> int:
        """Drop the whole episode plan (shots cascade via the FK)."""
        removed = self.episodes.delete_for_project(project.id)
        self.db.commit()
        return removed

    # ------------------------------------------------------------------- planning
    async def plan(
        self, project: Project, *, episode_count: int | None = None, replace: bool = False
    ) -> list[EpisodeOut]:
        """Run ``episode_planner`` and persist the outline.

        Without ``replace`` an existing plan is refused rather than silently
        replaced -- the same guard ``analyze`` uses, and for the same reason: a
        re-run would delete every script and storyboard the user already has.
        """
        desired = episode_count or DEFAULT_EPISODE_COUNT
        if not MIN_EPISODES <= desired <= MAX_EPISODES:
            raise ValidationError(f"集数必须在 {MIN_EPISODES}-{MAX_EPISODES} 之间")

        if project.analysis_status != SCRIPT_REQUIRED_ANALYSIS:
            raise ConflictError(
                "请先解析故事（生成 Story Bible），再规划分集",
                details={"analysis_status": project.analysis_status},
            )

        existing = self.episodes.count_for_project(project.id)
        if existing and not replace:
            raise ConflictError(
                f"项目已有 {existing} 集，请使用 replace=true 重新规划（会删除已有的剧本与分镜）",
                details={"episodes": existing},
            )

        story_bible, characters, locations = self._load_bibles(project)

        try:
            final_state = await run_episode_planner(
                project_id=str(project.id),
                story_text=(project.story_text or "").strip(),
                story_bible=story_bible,
                characters=characters,
                locations=locations,
                genre=project.genre,
                style=project.style,
                episode_count=desired,
                provider=self.provider,
            )
        except Exception:  # noqa: BLE001 -- recorded, then re-raised
            logger.exception("episode planner failed for project %s", project.id)
            raise

        plan = (final_state.get("episode_plan") or {}) or {}
        episodes = plan.get("episodes") or []
        if not episodes:
            raise ValidationError("分集大纲为空")

        return self._persist_plan(project, episodes, final_state, replace=bool(existing))

    def _persist_plan(
        self, project: Project, episodes: list[dict], state: dict, *, replace: bool
    ) -> list[EpisodeOut]:
        """Replace the plan in one transaction.

        Existing episodes are deleted rather than matched by number: the outline
        is a single generated artefact, and renumbering is exactly what a re-plan
        does, so "keep the script attached to episode 3" would be meaningless.
        """
        try:
            if replace:
                self.episodes.delete_for_project(project.id)
                self.db.flush()

            meta = {
                "provider": self.provider.name,
                "model": self.provider.model,
                "mock": self.provider.name == "mock",
                "prompt_versions": state.get("prompt_versions") or {},
                "usage": state.get("usage") or [],
                "generated_at": datetime.now(UTC).isoformat(),
            }
            for entry in episodes:
                self.episodes.create(
                    project_id=project.id,
                    episode_number=int(entry.get("episode_number") or 1),
                    title=entry.get("title"),
                    summary=entry.get("summary"),
                    duration=int(entry.get("duration") or 180),
                    status=EpisodeStatus.PLANNING.value,
                    generation_error=None,
                    script_status=GenerationStatus.NOT_GENERATED.value,
                    storyboard_status=GenerationStatus.NOT_GENERATED.value,
                )
            # Provenance of the *plan* is stored on the project so ``GET /episodes``
            # can report which model produced the outline.
            self._store_plan_meta(project, meta)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return self.list(project)

    def _store_plan_meta(self, project: Project, meta: dict) -> None:
        """Keep the plan's provenance on the project without clobbering the Bible.

        Stored under a separate key so the Story Bible's own ``_meta`` (which
        records the analysis run) stays intact -- both are needed to answer
        "what produced this?".
        """
        bible = dict(project.story_bible_json or {})
        bible["_episode_plan_meta"] = meta
        project.story_bible_json = bible

    def plan_meta(self, project: Project) -> dict | None:
        return dict(project.story_bible_json or {}).get("_episode_plan_meta")

    # --------------------------------------------------------------------- script
    async def generate_script(self, episode: Episode) -> Episode:
        """Run ``script_generator`` for one episode and persist the result."""
        project = self.get_project_for_episode(episode)
        if project.analysis_status != SCRIPT_REQUIRED_ANALYSIS:
            raise ConflictError(
                "请先解析故事（生成 Story Bible），再生成剧本",
                details={"analysis_status": project.analysis_status},
            )

        story_bible, characters, locations = self._load_bibles(project)

        episode.script_status = GenerationStatus.RUNNING.value
        episode.generation_error = None
        self.db.commit()

        try:
            final_state = await run_script_generator(
                project_id=str(project.id),
                episode_id=str(episode.id),
                episode_plan=self._episode_plan_payload(episode),
                story_bible=story_bible,
                characters=characters,
                locations=locations,
                story_text=(project.story_text or "").strip(),
                genre=project.genre,
                style=project.style,
                provider=self.provider,
            )
        except Exception as exc:  # noqa: BLE001 -- recorded, then re-raised
            logger.exception("script generator failed for episode %s", episode.id)
            episode.script_status = GenerationStatus.FAILED.value
            episode.generation_error = str(exc)[:2000]
            self.db.commit()
            raise

        return self._persist_script(episode, final_state)

    def _persist_script(self, episode: Episode, state: dict) -> Episode:
        try:
            script = dict(state.get("script") or {})
            script["_meta"] = {
                "provider": self.provider.name,
                "model": self.provider.model,
                "mock": self.provider.name == "mock",
                "prompt_versions": {
                    key: value
                    for key, value in (state.get("prompt_versions") or {}).items()
                    if key == "script_generator"
                },
                "usage": [
                    record
                    for record in (state.get("usage") or [])
                    if record.get("node") == "script_generator"
                ],
                "consistency": state.get("consistency") or {},
            }

            # Assigned in one go, and before any other ORM touch, for the reason
            # documented in docs/TDD.md: creating rows triggers an autoflush that
            # would persist a JSON column mid-edit, and SQLAlchemy does not track
            # in-place mutation of a JSON dict.
            episode.script_json = script
            episode.storyboard_json = None
            episode.storyboard_status = GenerationStatus.NOT_GENERATED.value
            episode.script_status = GenerationStatus.SUCCEEDED.value
            episode.generation_error = None
            episode.script_generated_at = datetime.now(UTC)
            episode.status = EpisodeStatus.SCRIPTING.value
            self.db.commit()

            # A new script invalidates the old storyboard's shots, so they are
            # removed rather than left pointing at scenes that no longer exist.
            self.shots.delete_for_episode(episode.id)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return episode

    def update_script(
        self, user_id: uuid.UUID, episode_id: uuid.UUID, payload: ScriptUpdate
    ) -> Episode:
        """Hand-edit the script document."""
        episode = self.get_model(user_id, episode_id)
        stored = dict(episode.script_json or {})
        if not stored:
            raise NotFoundError("该剧集还没有剧本")

        changes = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not changes:
            raise ValidationError("没有需要更新的字段")

        content = dict(stored)
        for field, value in changes.items():
            if field == "scenes":
                content["scenes"] = [
                    scene.model_dump() if hasattr(scene, "model_dump") else scene for scene in value
                ]
            else:
                content[field] = value

        # Validate before storing, so a hand-edit cannot write a script that the
        # storyboard generator would not be able to consume.
        validated = ScriptContent.model_validate({k: v for k, v in content.items() if k != "_meta"})
        stored.update(validated.model_dump())
        episode.script_json = stored
        self.db.commit()
        self.db.refresh(episode)
        return episode

    # ----------------------------------------------------------------- storyboard
    async def generate_storyboard(self, episode: Episode) -> Episode:
        """Run ``storyboard_generator -> consistency_checker`` and persist shots."""
        project = self.get_project_for_episode(episode)
        script = dict(episode.script_json or {})
        if not script.get("scenes"):
            raise ConflictError("请先生成本集剧本，再生成分镜")

        story_bible, characters, locations = self._load_bibles(project)

        episode.storyboard_status = GenerationStatus.RUNNING.value
        episode.generation_error = None
        self.db.commit()

        try:
            final_state = await run_storyboard_generator(
                project_id=str(project.id),
                episode_id=str(episode.id),
                script=script,
                story_bible=story_bible,
                characters=characters,
                locations=locations,
                episode_plan=self._episode_plan_payload(episode),
                story_text=(project.story_text or "").strip(),
                genre=project.genre,
                style=project.style,
                provider=self.provider,
            )
        except Exception as exc:  # noqa: BLE001 -- recorded, then re-raised
            logger.exception("storyboard generator failed for episode %s", episode.id)
            episode.storyboard_status = GenerationStatus.FAILED.value
            episode.generation_error = str(exc)[:2000]
            self.db.commit()
            raise

        return self._persist_storyboard(episode, final_state)

    def _persist_storyboard(self, episode: Episode, state: dict) -> Episode:
        try:
            storyboard = dict(state.get("storyboard") or {})
            storyboard["_meta"] = {
                "provider": self.provider.name,
                "model": self.provider.model,
                "mock": self.provider.name == "mock",
                "prompt_versions": {
                    key: value
                    for key, value in (state.get("prompt_versions") or {}).items()
                    if key == "storyboard_generator"
                },
                "usage": [
                    record
                    for record in (state.get("usage") or [])
                    if record.get("node") == "storyboard_generator"
                ],
                "consistency": state.get("consistency") or {},
            }

            # Shots are rebuilt from scratch on every generation: they are the
            # rows Phase 5-7 hang media off, and new content means the old media
            # no longer belongs to them (see the module docstring).
            self.shots.delete_for_episode(episode.id)

            sequence = 0
            for scene in storyboard.get("scenes") or []:
                scene_id = str(scene.get("scene_id") or "")
                if not scene_id:
                    continue
                for shot in scene.get("shots") or []:
                    sequence += 1
                    self.shots.create(
                        episode_id=episode.id,
                        scene_id=scene_id,
                        shot_number=int(shot.get("shot_number") or sequence),
                        sequence=sequence,
                        duration=int(shot.get("duration") or 5),
                        shot_size=str(shot.get("shot_size") or "medium"),
                        camera_movement=str(shot.get("camera_movement") or "static"),
                        characters_json=list(shot.get("characters") or []),
                        action=shot.get("action"),
                        expression=shot.get("expression"),
                        dialogue=shot.get("dialogue"),
                        visual_description=shot.get("visual_description"),
                        image_prompt=shot.get("image_prompt"),
                        video_prompt=shot.get("video_prompt"),
                    )

            episode.storyboard_json = storyboard
            episode.storyboard_status = GenerationStatus.SUCCEEDED.value
            episode.generation_error = None
            episode.storyboard_generated_at = datetime.now(UTC)
            episode.status = EpisodeStatus.STORYBOARDING.value
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return episode

    def update_storyboard(
        self, user_id: uuid.UUID, episode_id: uuid.UUID, payload: StoryboardUpdate
    ) -> Episode:
        episode = self.get_model(user_id, episode_id)
        stored = dict(episode.storyboard_json or {})
        if not stored:
            raise NotFoundError("该剧集还没有分镜")

        changes = payload.model_dump(exclude_unset=True, exclude_none=True)
        if not changes:
            raise ValidationError("没有需要更新的字段")

        validated = StoryboardContent.model_validate({"scenes": changes.get("scenes") or []})
        stored["scenes"] = validated.model_dump()["scenes"]
        episode.storyboard_json = stored

        # Mirror the edit into the rows, since Phases 5-7 read shots, not JSON.
        self.shots.delete_for_episode(episode.id)
        sequence = 0
        for scene in stored["scenes"]:
            for shot in scene.get("shots") or []:
                sequence += 1
                self.shots.create(
                    episode_id=episode.id,
                    scene_id=str(scene.get("scene_id")),
                    shot_number=int(shot.get("shot_number") or sequence),
                    sequence=sequence,
                    duration=int(shot.get("duration") or 5),
                    shot_size=str(shot.get("shot_size") or "medium"),
                    camera_movement=str(shot.get("camera_movement") or "static"),
                    characters_json=list(shot.get("characters") or []),
                    action=shot.get("action"),
                    expression=shot.get("expression"),
                    dialogue=shot.get("dialogue"),
                    visual_description=shot.get("visual_description"),
                    image_prompt=shot.get("image_prompt"),
                    video_prompt=shot.get("video_prompt"),
                )
        self.db.commit()
        self.db.refresh(episode)
        return episode

    # -------------------------------------------------------------- consistency
    def check(self, episode: Episode) -> ConsistencyReport:
        """Re-audit the stored script/storyboard without calling a provider.

        Free and deterministic, so the UI can re-check after a hand-edit.

        Both documents are audited. Checking only the storyboard would make this
        endpoint's report disagree with the one stored during generation, since
        the script-level findings (speaker not in scene, scene without dialogue)
        would silently disappear.
        """
        project = self.get_project_for_episode(episode)
        _, characters, locations = self._load_bibles(project)
        script = dict(episode.script_json or {})

        character_ids = {item["id"]: item["name"] for item in characters}
        location_ids = {item["id"]: item["name"] for item in locations}

        issues = [
            *check_script_bindings(script, character_ids, location_ids),
            *check_storyboard(
                dict(episode.storyboard_json or {}),
                script=script,
                characters=characters,
                locations=locations,
                episode_duration=episode.duration or None,
                style=project.style,
            ).issues,
        ]

        return ConsistencyReport(
            issues=issues,
            checked_shots=sum(
                1
                for scene in (dict(episode.storyboard_json or {}).get("scenes") or [])
                for _ in scene.get("shots") or []
            ),
            checked_scenes=len(dict(episode.storyboard_json or {}).get("scenes") or []),
        )

    # ------------------------------------------------------------------- helpers
    def _load_bibles(self, project: Project) -> tuple[dict, list[dict], list[dict]]:
        """Story Bible + characters + locations, as plain dicts with ids."""
        bible = {
            key: value
            for key, value in (project.story_bible_json or {}).items()
            if not key.startswith("_")
        }
        characters = [
            self._character_payload(row) for row in self.characters.list_for_project(project.id)
        ]
        locations = [
            self._location_payload(row) for row in self.locations.list_for_project(project.id)
        ]
        return bible, characters, locations

    @staticmethod
    def _character_payload(row) -> dict:
        return {
            "id": str(row.id),
            "name": row.name,
            "role": row.role,
            "age": row.age,
            "gender": row.gender,
            "description": row.description,
            "appearance": row.appearance,
            "hair": row.hair,
            "clothing": row.clothing,
            "personality": row.personality,
        }

    @staticmethod
    def _location_payload(row) -> dict:
        return {
            "id": str(row.id),
            "name": row.name,
            "description": row.description,
            "time": row.time,
            "lighting": row.lighting,
            "visual_style": row.visual_style,
        }

    @staticmethod
    def _episode_plan_payload(episode: Episode) -> dict:
        return {
            "episode_id": str(episode.id),
            "episode_number": episode.episode_number,
            "title": episode.title,
            "summary": episode.summary,
            "duration": episode.duration,
        }

    @staticmethod
    def _to_out(episode: Episode, *, shot_count: int = 0) -> EpisodeOut:
        return EpisodeOut(
            id=episode.id,
            project_id=episode.project_id,
            episode_number=episode.episode_number,
            title=episode.title,
            summary=episode.summary,
            duration=episode.duration,
            status=episode.status,
            script_status=episode.script_status,
            storyboard_status=episode.storyboard_status,
            generation_error=episode.generation_error,
            script_generated_at=episode.script_generated_at,
            storyboard_generated_at=episode.storyboard_generated_at,
            has_script=bool(episode.script_json),
            has_storyboard=bool(episode.storyboard_json),
            shot_count=shot_count,
            created_at=episode.created_at,
            updated_at=episode.updated_at,
        )


__all__ = [
    "DEFAULT_EPISODE_COUNT",
    "MAX_EPISODES",
    "MIN_EPISODES",
    "EpisodeService",
]
