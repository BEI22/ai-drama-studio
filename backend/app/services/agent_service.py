"""Story Agent orchestration + persistence (PRD sections 12, 37).

Runs the LangGraph workflow and writes the result into ``story_bible_json``,
``characters`` and ``locations``. This is the layer that turns agent output into
committed database state, so all of that happens in one transaction: either the
project ends up fully analyzed or it stays untouched with ``analysis_status =
FAILED`` and a readable error.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agents import run_story_agent
from app.core.config import settings
from app.core.exceptions import ConflictError, ValidationError
from app.models.character import Character
from app.models.enums import AnalysisStatus
from app.models.location import Location
from app.models.project import Project
from app.providers.base import LLMProvider
from app.providers.llm.factory import get_llm_provider
from app.repositories.character import CharacterRepository
from app.repositories.location import LocationRepository
from app.repositories.project import ProjectRepository
from app.schemas.bible import CharacterDraft, LocationDraft

logger = logging.getLogger(__name__)

MIN_STORY_LENGTH = 10


class AgentService:
    """Analyze a project's story into a Story Bible + characters + locations."""

    def __init__(self, db: Session, *, provider: LLMProvider | None = None) -> None:
        self.db = db
        self.projects = ProjectRepository(db)
        self.characters = CharacterRepository(db)
        self.locations = LocationRepository(db)
        # Injected in tests; resolved lazily so settings are read per-process.
        self._provider = provider

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = get_llm_provider()
        return self._provider

    # ------------------------------------------------------------------ analyze
    async def analyze(
        self,
        project: Project,
        *,
        replace: bool = False,
        story_text: str | None = None,
    ) -> Project:
        """Run the Story Agent and persist the result.

        ``story_text`` lets a caller analyze a candidate text without saving it
        first. ``replace`` overwrites existing characters/locations; without it, a
        project that already has them is refused rather than silently doubled.
        """
        text = (story_text if story_text is not None else project.story_text or "").strip()
        if len(text) < MIN_STORY_LENGTH:
            raise ValidationError(
                f"故事文本过短（至少 {MIN_STORY_LENGTH} 字），无法解析",
                details={"field": "story_text", "min_length": MIN_STORY_LENGTH},
            )

        # The conflict guard keys off the *analysis state*, not off whether rows
        # happen to exist. Editing the story sets the status back to
        # NOT_ANALYZED while leaving the old cast behind; in that case re-running
        # is exactly what the user asked for, so it must not be refused.
        already_analyzed = project.analysis_status == AnalysisStatus.SUCCEEDED.value
        if already_analyzed and not replace:
            raise ConflictError(
                "项目已经解析过，请使用 replace=true 重新解析（会覆盖现有人物与场景）",
                details={"characters": self.characters.count_for_project(project.id)},
            )

        # Re-running an invalidated or failed analysis has to clean up the stale
        # rows, otherwise a changed story would leave orphaned characters behind.
        effective_replace = replace or not already_analyzed

        project.analysis_status = AnalysisStatus.RUNNING.value
        project.analysis_error = None
        self.db.commit()

        try:
            final_state = await run_story_agent(
                project_id=str(project.id),
                story_text=text,
                genre=project.genre,
                style=project.style,
                project_name=project.name,
                provider=self.provider,
            )
        except Exception as exc:  # noqa: BLE001 -- recorded, then re-raised
            logger.exception("story agent failed for project %s", project.id)
            project.analysis_status = AnalysisStatus.FAILED.value
            project.analysis_error = str(exc)[:2000]
            project.analyzed_at = datetime.now(UTC)
            self.db.commit()
            raise

        self._persist(project, final_state, replace=effective_replace)
        return project

    # ------------------------------------------------------------------ persist
    def _persist(self, project: Project, state: dict, *, replace: bool) -> None:
        """Write the workflow result. One transaction for the whole Bible.

        Characters and locations are **upserted by name**, not wiped and
        recreated:

        * their primary keys stay stable, which Phase 4+ needs -- shots will
          reference ``character_id``;
        * a user's hand-edits to the visual fields survive a re-analysis (see
          ``_apply_character``).

        With ``replace`` the rows the agent no longer produces are removed, so
        "re-analyze" still means what a user expects.
        """
        try:
            existing_characters = {
                row.name.casefold(): row for row in self.characters.list_for_project(project.id)
            }
            existing_locations = {
                row.name.casefold(): row for row in self.locations.list_for_project(project.id)
            }

            project.story_bible_json = state.get("story_bible") or None

            kept_characters: set[str] = set()
            for character in state.get("characters") or []:
                draft = CharacterDraft.model_validate(character)
                key = draft.name.casefold()
                kept_characters.add(key)

                row = existing_characters.get(key)
                if row is not None:
                    self._apply_character(row, draft)
                    continue
                self.characters.create(project_id=project.id, **self._character_values(draft))

            kept_locations: set[str] = set()
            for location in state.get("locations") or []:
                draft = LocationDraft.model_validate(location)
                key = draft.name.casefold()
                kept_locations.add(key)

                row = existing_locations.get(key)
                if row is not None:
                    self._apply_location(row, draft)
                    continue
                self.locations.create(project_id=project.id, **self._location_values(draft))

            if replace:
                for key, row in existing_characters.items():
                    if key not in kept_characters:
                        self.db.delete(row)
                for key, row in existing_locations.items():
                    if key not in kept_locations:
                        self.db.delete(row)

            # Record which provider produced this, so mock output is never
            # mistaken for real model output.
            if project.story_bible_json is not None:
                project.story_bible_json["_meta"] = {
                    "provider": self.provider.name,
                    "model": self.provider.model,
                    "mock": self.provider.name == "mock",
                    "prompt_versions": state.get("prompt_versions") or {},
                    "usage": state.get("usage") or [],
                    "max_retries": settings.llm_max_retries,
                }

            project.analysis_status = AnalysisStatus.SUCCEEDED.value
            project.analysis_error = None
            project.analyzed_at = datetime.now(UTC)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _character_values(draft: CharacterDraft) -> dict:
        return {
            "name": draft.name,
            "role": draft.role.value,
            "age": draft.age,
            "gender": draft.gender,
            "description": draft.description,
            "appearance": draft.appearance,
            "hair": draft.hair,
            "clothing": draft.clothing,
            "personality": draft.personality,
            "sort_order": draft.sort_order,
        }

    @staticmethod
    def _location_values(draft: LocationDraft) -> dict:
        return {
            "name": draft.name,
            "description": draft.description,
            "time": draft.time,
            "lighting": draft.lighting,
            "visual_style": draft.visual_style,
            "sort_order": draft.sort_order,
        }

    @classmethod
    def _apply_character(cls, row: Character, draft: CharacterDraft) -> None:
        for field, value in cls._character_values(draft).items():
            # Keep user hand-edits of appearance/clothing: only refresh the
            # fields the agent is authoritative for.
            if field in {"appearance", "clothing", "hair"} and getattr(row, field):
                continue
            setattr(row, field, value)

    @classmethod
    def _apply_location(cls, row: Location, draft: LocationDraft) -> None:
        for field, value in cls._location_values(draft).items():
            if field == "description" and row.description:
                continue
            setattr(row, field, value)

    # -------------------------------------------------------------- run status
    def status(self, project: Project) -> dict:
        return {
            "analysis_status": project.analysis_status,
            "analysis_error": project.analysis_error,
            "analyzed_at": project.analyzed_at,
            "characters": self.characters.count_for_project(project.id),
            "locations": self.locations.count_for_project(project.id),
            "provider": self.provider.name,
            "model": self.provider.model,
            "mock": self.provider.name == "mock",
        }


__all__ = ["MIN_STORY_LENGTH", "AgentService"]
