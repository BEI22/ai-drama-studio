"""Story Agent + Character/Location Bible routes (PRD sections 22, 37).

    POST   /api/v1/projects/{id}/analyze                    -> run the Story Agent
    GET    /api/v1/projects/{id}/analyze/status             -> run state + counts
    GET    /api/v1/projects/{id}/bible                      -> Story Bible + cast + scenes
    GET    /api/v1/projects/{id}/characters                 -> Character Bible
    POST   /api/v1/projects/{id}/characters
    GET    /api/v1/projects/{id}/locations                  -> Scene Bible
    POST   /api/v1/projects/{id}/locations
    PATCH  /api/v1/characters/{character_id}
    DELETE /api/v1/characters/{character_id}
    PATCH  /api/v1/locations/{location_id}
    DELETE /api/v1/locations/{location_id}

PRD section 37 items 17-18: users must be able to modify the extracted characters
and locations, so these are full CRUD rather than read-only agent output.

Note on ``analyze``: this is deliberately one synchronous request. It runs three
short LLM calls, which is fine for Phase 3; PRD section 21's "long tasks must be
async" rule targets image/video/TTS (Phases 5+), not the text workflow.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Query
from pydantic import ValidationError

from app.api.deps import (
    AgentServiceDep,
    CharacterServiceDep,
    CurrentUser,
    LocationServiceDep,
    ProjectServiceDep,
)
from app.core.responses import ok
from app.schemas.bible import (
    CharacterCreate,
    CharacterOut,
    CharacterUpdate,
    LocationCreate,
    LocationOut,
    LocationUpdate,
    StoryBibleContent,
    StoryBibleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["story-agent"])


# ------------------------------------------------------------------ composing
def compose_bible(
    project,
    characters: list[CharacterOut],
    locations: list[LocationOut],
) -> dict:
    """Build the Story Bible payload.

    ``story_bible_json`` holds the world/setting half plus a ``_meta`` provenance
    block; characters and locations are nested in from their own tables so there
    is a single source of truth (see docs/TDD.md section 17).
    """
    stored = dict(project.story_bible_json or {})
    meta = stored.pop("_meta", None)

    content: StoryBibleContent | None = None
    if stored:
        try:
            content = StoryBibleContent.model_validate(stored)
        except ValidationError as exc:
            # Rows written before a schema change, or edited directly in the DB.
            # Surface the rest of the page instead of failing the whole request.
            logger.warning(
                "stored story bible failed validation for project %s (%d errors)",
                project.id,
                exc.error_count(),
            )

    return StoryBibleResponse(
        project_id=project.id,
        analysis_status=project.analysis_status,
        analysis_error=project.analysis_error,
        analyzed_at=project.analyzed_at,
        story_bible=content,
        characters=characters,
        locations=locations,
        meta=meta,
    ).model_dump(mode="json")


# ------------------------------------------------------------------- analysis
@router.post("/projects/{project_id}/analyze", summary="解析故事（Story Agent）")
async def analyze_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    agents: AgentServiceDep,
    characters: CharacterServiceDep,
    locations: LocationServiceDep,
    replace: Annotated[bool, Query(description="覆盖已有人物与场景")] = False,
    story_text: Annotated[
        str | None,
        Body(embed=True, description="可选：解析这段文本而不修改项目已保存的故事"),
    ] = None,
) -> dict:
    """Run ``story_parser -> character_extractor -> location_extractor``.

    Returns 409 if the project already has characters and ``replace`` is false, so
    a re-run can never silently double the cast.
    """
    project = projects.get_model(user, project_id)
    await agents.analyze(project, replace=replace, story_text=story_text)

    logger.info(
        "story analyzed",
        extra={
            "project_id": str(project_id),
            "provider": agents.provider.name,
        },
    )
    return ok(compose_bible(project, characters.list(project), locations.list(project)))


@router.get("/projects/{project_id}/analyze/status", summary="解析状态")
def analyze_status(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    agents: AgentServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    return ok(agents.status(project))


# ------------------------------------------------------------------ story bible
@router.get("/projects/{project_id}/bible", summary="Story Bible（含人物与场景）")
def get_bible(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    characters: CharacterServiceDep,
    locations: LocationServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    return ok(compose_bible(project, characters.list(project), locations.list(project)))


# ------------------------------------------------------------------- characters
@router.get("/projects/{project_id}/characters", summary="人物列表")
def list_characters(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    characters: CharacterServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    return ok([item.model_dump(mode="json") for item in characters.list(project)])


@router.post("/projects/{project_id}/characters", summary="手动添加人物")
def create_character(
    project_id: uuid.UUID,
    payload: CharacterCreate,
    user: CurrentUser,
    projects: ProjectServiceDep,
    characters: CharacterServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    created = characters.create(project, payload)
    return ok(created.model_dump(mode="json"))


@router.patch("/characters/{character_id}", summary="修改人物")
def update_character(
    character_id: uuid.UUID,
    payload: CharacterUpdate,
    user: CurrentUser,
    characters: CharacterServiceDep,
) -> dict:
    updated = characters.update(user.id, character_id, payload)
    return ok(updated.model_dump(mode="json"))


@router.delete("/characters/{character_id}", summary="删除人物")
def delete_character(
    character_id: uuid.UUID,
    user: CurrentUser,
    characters: CharacterServiceDep,
) -> dict:
    characters.delete(user.id, character_id)
    return ok({"id": str(character_id), "deleted": True})


# -------------------------------------------------------------------- locations
@router.get("/projects/{project_id}/locations", summary="场景列表")
def list_locations(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    locations: LocationServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    return ok([item.model_dump(mode="json") for item in locations.list(project)])


@router.post("/projects/{project_id}/locations", summary="手动添加场景")
def create_location(
    project_id: uuid.UUID,
    payload: LocationCreate,
    user: CurrentUser,
    projects: ProjectServiceDep,
    locations: LocationServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    created = locations.create(project, payload)
    return ok(created.model_dump(mode="json"))


@router.patch("/locations/{location_id}", summary="修改场景")
def update_location(
    location_id: uuid.UUID,
    payload: LocationUpdate,
    user: CurrentUser,
    locations: LocationServiceDep,
) -> dict:
    updated = locations.update(user.id, location_id, payload)
    return ok(updated.model_dump(mode="json"))


@router.delete("/locations/{location_id}", summary="删除场景")
def delete_location(
    location_id: uuid.UUID,
    user: CurrentUser,
    locations: LocationServiceDep,
) -> dict:
    locations.delete(user.id, location_id)
    return ok({"id": str(location_id), "deleted": True})


__all__ = ["compose_bible", "router"]
