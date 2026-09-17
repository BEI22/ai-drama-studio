"""Episode Agent routes (PRD sections 22, 38 -- Phase 4).

    GET    /api/v1/projects/{id}/episodes                    -> episode list
    POST   /api/v1/projects/{id}/episodes                    -> add one episode manually
    POST   /api/v1/projects/{id}/episodes/plan               -> run the planner
    DELETE /api/v1/projects/{id}/episodes                    -> drop the whole plan
    GET    /api/v1/episodes/{id}                             -> one episode
    PATCH  /api/v1/episodes/{id}
    DELETE /api/v1/episodes/{id}

    GET    /api/v1/episodes/{id}/script                      -> script document
    POST   /api/v1/episodes/{id}/script/generate             -> run the script generator
    PATCH  /api/v1/episodes/{id}/script                      -> hand-edit

    GET    /api/v1/episodes/{id}/storyboard                  -> storyboard + shots
    POST   /api/v1/episodes/{id}/storyboard/generate         -> shots + consistency
    PATCH  /api/v1/episodes/{id}/storyboard

    GET    /api/v1/episodes/{id}/shots                       -> flat shot list
    PATCH  /api/v1/shots/{id}                                -> edit one shot
    GET    /api/v1/episodes/{id}/consistency                 -> re-audit, no provider

Like ``analyze`` in Phase 3, the generate endpoints are synchronous: they run one
or two short LLM calls. PRD section 21's "long tasks must be async" rule targets
image/video/TTS (Phases 5+), not this text workflow.

``characters`` in a script response are returned as ids (that is what the script
stores and what PRD section 10 mandates). The response also carries a
``characters`` lookup on the episode so a UI can render names without a second
request.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import ValidationError as PydanticValidationError

from app.api.deps import (
    CharacterServiceDep,
    CurrentUser,
    EpisodeServiceDep,
    ImageServiceDep,
    LocationServiceDep,
    ProjectServiceDep,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.core.responses import ok
from app.schemas.episode import (
    EpisodeCreate,
    EpisodeUpdate,
    ScriptContent,
    ScriptResponse,
    ScriptUpdate,
    ShotOut,
    ShotUpdate,
    StoryboardContent,
    StoryboardResponse,
    StoryboardUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["episode-agent"])


# ------------------------------------------------------------------- composing
def compose_script(episode, characters: dict[str, str]) -> dict:
    """Script document + the id->name lookup the UI needs to render it."""
    stored = dict(episode.script_json or {})
    meta = stored.pop("_meta", None)

    content: ScriptContent | None = None
    if stored:
        try:
            content = ScriptContent.model_validate(stored)
        except PydanticValidationError as exc:
            # Written before a schema change, or edited straight in the DB.
            logger.warning(
                "stored script failed validation for episode %s (%d errors)",
                episode.id,
                exc.error_count(),
            )

    return ScriptResponse(
        episode_id=episode.id,
        script_status=episode.script_status,
        has_script=bool(episode.script_json),
        script=content,
        meta=meta,
    ).model_dump(mode="json") | {"characters": characters}


def compose_storyboard(
    episode,
    shots: list[ShotOut],
    consistency,
    characters: dict[str, str],
    media: dict[str, dict] | None = None,
) -> dict:
    """Storyboard document + flat shot rows + the latest consistency report."""
    stored = dict(episode.storyboard_json or {})
    meta = stored.pop("_meta", None)

    content: StoryboardContent | None = None
    if stored:
        try:
            content = StoryboardContent.model_validate(stored)
        except PydanticValidationError as exc:
            logger.warning(
                "stored storyboard failed validation for episode %s (%d errors)",
                episode.id,
                exc.error_count(),
            )

    return StoryboardResponse(
        episode_id=episode.id,
        storyboard_status=episode.storyboard_status,
        has_storyboard=bool(episode.storyboard_json),
        storyboard=content,
        shots=shots,
        consistency=consistency,
        meta=meta,
        media=media or {},
    ).model_dump(mode="json") | {"characters": characters}


# -------------------------------------------------------------------- episodes
@router.get("/projects/{project_id}/episodes", summary="剧集列表")
def list_episodes(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
    locations: LocationServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    items = [item.model_dump(mode="json") for item in episodes.list(project)]
    return ok(
        {
            "items": items,
            "totals": {
                "episodes": len(items),
                "characters": len(characters.list(project)),
                "locations": len(locations.list(project)),
            },
            "plan_meta": episodes.plan_meta(project),
            "analysis_status": project.analysis_status,
        }
    )


@router.post("/projects/{project_id}/episodes", summary="手动新增剧集")
def create_episode(
    project_id: uuid.UUID,
    payload: EpisodeCreate,
    user: CurrentUser,
    projects: ProjectServiceDep,
    episodes: EpisodeServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    created = episodes.create(project, payload)
    return ok(created.model_dump(mode="json"))


@router.post("/projects/{project_id}/episodes/plan", summary="规划分集（Episode Agent）")
async def plan_episodes(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
    locations: LocationServiceDep,
    replace: Annotated[bool, Query(description="覆盖已有的剧集（会删除已有剧本与分镜）")] = False,
    episode_count: Annotated[
        int | None, Query(ge=1, le=24, description="期望集数（默认 6）")
    ] = None,
) -> dict:
    """Run ``episode_planner`` and persist the outline.

    Returns 409 when the story has not been analyzed, or when a plan already
    exists and ``replace`` is false -- so a re-run can never silently destroy
    scripts and storyboards.
    """
    project = projects.get_model(user, project_id)
    await episodes.plan(project, episode_count=episode_count, replace=replace)

    logger.info(
        "episodes planned",
        extra={"project_id": str(project_id), "provider": episodes.provider.name},
    )
    return ok(
        {
            "items": [item.model_dump(mode="json") for item in episodes.list(project)],
            "plan_meta": episodes.plan_meta(project),
        }
    )


@router.delete("/projects/{project_id}/episodes", summary="清空分集计划")
def delete_episodes(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    episodes: EpisodeServiceDep,
) -> dict:
    project = projects.get_model(user, project_id)
    removed = episodes.delete_all(project)
    return ok({"deleted": removed})


@router.get("/episodes/{episode_id}", summary="剧集详情")
def get_episode(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
) -> dict:
    return ok(episodes.get_out(user.id, episode_id).model_dump(mode="json"))


@router.patch("/episodes/{episode_id}", summary="修改剧集")
def update_episode(
    episode_id: uuid.UUID,
    payload: EpisodeUpdate,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
) -> dict:
    updated = episodes.update(user.id, episode_id, payload)
    return ok(updated.model_dump(mode="json"))


@router.delete("/episodes/{episode_id}", summary="删除剧集")
def delete_episode(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
) -> dict:
    episodes.delete(user.id, episode_id)
    return ok({"id": str(episode_id), "deleted": True})


# ---------------------------------------------------------------------- script
def _character_lookup(characters) -> dict[str, str]:
    return {str(item.id): item.name for item in characters}


@router.get("/episodes/{episode_id}/script", summary="剧集剧本")
def get_script(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
) -> dict:
    episode = episodes.get_model(user.id, episode_id)
    project = episodes.get_project_for_episode(episode)
    return ok(compose_script(episode, _character_lookup(characters.list(project))))


@router.post("/episodes/{episode_id}/script/generate", summary="生成剧本（Script Generator）")
async def generate_script(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
) -> dict:
    """Run ``script_generator`` for this episode.

    Every ``character_id`` / ``location_id`` in the result is bound to a real row
    (PRD section 10); the node retries the model if it invents one.
    """
    episode = episodes.get_model(user.id, episode_id)
    await episodes.generate_script(episode)
    project = episodes.get_project_for_episode(episode)

    logger.info(
        "script generated",
        extra={"episode_id": str(episode_id), "provider": episodes.provider.name},
    )
    return ok(compose_script(episode, _character_lookup(characters.list(project))))


@router.patch("/episodes/{episode_id}/script", summary="修改剧本")
def update_script(
    episode_id: uuid.UUID,
    payload: ScriptUpdate,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
) -> dict:
    episode = episodes.update_script(user.id, episode_id, payload)
    project = episodes.get_project_for_episode(episode)
    return ok(compose_script(episode, _character_lookup(characters.list(project))))


# ------------------------------------------------------------------ storyboard
@router.get("/episodes/{episode_id}/storyboard", summary="剧集分镜")
def get_storyboard(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
    images: ImageServiceDep,
) -> dict:
    episode = episodes.get_model(user.id, episode_id)
    project = episodes.get_project_for_episode(episode)
    shot_rows = episodes.shots.list_for_episode(episode.id)
    shots = [ShotOut.model_validate(row).model_dump(mode="json") for row in shot_rows]
    return ok(
        compose_storyboard(
            episode,
            shots,
            episodes.check(episode),
            _character_lookup(characters.list(project)),
            # Phase 5: each shot's picture state, so the storyboard renders in one
            # request (assets, attempt count, and the task to poll while running).
            media=images.shot_media_map(shot_rows),
        )
    )


@router.post(
    "/episodes/{episode_id}/storyboard/generate",
    summary="生成分镜（Storyboard Generator + Consistency Checker）",
)
async def generate_storyboard(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
) -> dict:
    """Run ``storyboard_generator -> consistency_checker`` and persist shots."""
    episode = episodes.get_model(user.id, episode_id)
    await episodes.generate_storyboard(episode)
    project = episodes.get_project_for_episode(episode)

    shots = [
        ShotOut.model_validate(row).model_dump(mode="json")
        for row in episodes.shots.list_for_episode(episode.id)
    ]
    logger.info(
        "storyboard generated",
        extra={"episode_id": str(episode_id), "shots": len(shots)},
    )
    return ok(
        compose_storyboard(
            episode, shots, episodes.check(episode), _character_lookup(characters.list(project))
        )
    )


@router.patch("/episodes/{episode_id}/storyboard", summary="修改分镜")
def update_storyboard(
    episode_id: uuid.UUID,
    payload: StoryboardUpdate,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    characters: CharacterServiceDep,
) -> dict:
    episode = episodes.update_storyboard(user.id, episode_id, payload)
    project = episodes.get_project_for_episode(episode)
    shots = [
        ShotOut.model_validate(row).model_dump(mode="json")
        for row in episodes.shots.list_for_episode(episode.id)
    ]
    return ok(
        compose_storyboard(
            episode, shots, episodes.check(episode), _character_lookup(characters.list(project))
        )
    )


# ----------------------------------------------------------------------- shots
@router.get("/episodes/{episode_id}/shots", summary="分镜镜头列表")
def list_shots(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
) -> dict:
    episode = episodes.get_model(user.id, episode_id)
    rows = episodes.shots.list_for_episode(episode.id)
    return ok([ShotOut.model_validate(row).model_dump(mode="json") for row in rows])


@router.patch("/shots/{shot_id}", summary="修改单个镜头")
def update_shot(
    shot_id: uuid.UUID,
    payload: ShotUpdate,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
) -> dict:
    shot = episodes.shots.get_for_user(shot_id, user.id)
    if shot is None:
        raise NotFoundError("镜头不存在")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationError("没有需要更新的字段")

    for field, value in changes.items():
        if field == "characters":
            shot.characters_json = value
            continue
        if value is not None and hasattr(value, "value"):
            value = value.value
        setattr(shot, field, value)

    episodes.db.commit()
    episodes.db.refresh(shot)
    return ok(ShotOut.model_validate(shot).model_dump(mode="json"))


# ----------------------------------------------------------------- consistency
@router.get("/episodes/{episode_id}/consistency", summary="一致性检查（不调用模型）")
def check_consistency(
    episode_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
) -> dict:
    """Re-audit the stored storyboard. Deterministic, no provider call."""
    episode = episodes.get_model(user.id, episode_id)
    report = episodes.check(episode)
    return ok(
        {
            "episode_id": str(episode.id),
            **report.model_dump(mode="json"),
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "ok": report.ok,
        }
    )


__all__ = ["compose_script", "compose_storyboard", "router"]
