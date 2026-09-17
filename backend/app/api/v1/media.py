"""Media routes: images and generation tasks (PRD sections 21, 22 -- Phase 5).

PRD section 22 fixes this surface:

    POST /api/shots/{shot_id}/image/generate     -> queue one shot's image
    POST /api/shots/{shot_id}/video/generate     -> Phase 6
    POST /api/shots/{shot_id}/audio/generate     -> Phase 7
    POST /api/shots/{shot_id}/regenerate         -> re-roll the shot's media
    GET  /api/tasks/{task_id}
    GET  /api/projects/{project_id}/tasks
    POST /api/tasks/{task_id}/retry

Every generate endpoint **accepts and returns** rather than doing the work: it
writes a ``PENDING`` generation_task and publishes it to the queue, then hands
back the task row for the client to poll (PRD section 21, section 30 principle 4).
The image itself is produced by the Celery worker.

➕ Beyond section 22 (recorded in docs/TDD.md section 19.7):
    POST /api/characters/{character_id}/reference/generate
    POST /api/locations/{location_id}/reference/generate
    POST /api/episodes/{episode_id}/images/generate
    GET  /api/projects/{project_id}/assets
Section 31 lists Character Reference / Location Reference as Phase 5 deliverables
but section 22 gives them no routes; the third is the "generate the whole
episode" action, without which a 50-shot episode is 50 clicks; the last backs the
素材 page that section 5.3 puts in the project navigation, which section 22 leaves
without a data source.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import (
    CharacterServiceDep,
    CurrentUser,
    EpisodeServiceDep,
    ImageServiceDep,
    LocationServiceDep,
    ProjectServiceDep,
)
from app.core.exceptions import ConflictError, NotFoundError, UnsupportedError
from app.core.responses import ok
from app.models.enums import AssetType, TaskStatus, TaskType
from app.schemas.media import TaskAcceptedOut, TaskOut
from app.services.image_service import asset_to_dict, task_to_dict
from app.tasks import enqueue_image_task

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])


def _project_of_shot(episodes, user_id: uuid.UUID, shot):
    """The project a shot belongs to, via its episode.

    ``ProjectService.get_model`` takes a *project* id, and a shot only carries
    ``episode_id``, so the hop through the episode is required -- passing the
    episode id there would look up a project that does not exist.
    """
    return episodes.get_project_for_episode(episodes.get_model(user_id, shot.episode_id))


def _load_shot(episodes, shot_id: uuid.UUID, user_id: uuid.UUID):
    """Fetch a shot, ownership-scoped -- same shape as ``PATCH /shots/{id}``."""
    shot = episodes.shots.get_for_user(shot_id, user_id)
    if shot is None:
        raise NotFoundError("镜头不存在")
    return shot


# Serialisation lives in the service so the media routes and the storyboard
# response cannot drift apart; these are aliases for readability at call sites.
task_out = task_to_dict
asset_out = asset_to_dict


def _accept(task, reused: bool) -> dict:
    """Queue the task unless it was already live, then return it for polling."""
    if not reused:
        enqueue_image_task(task.id)
    payload = TaskAcceptedOut(
        task=TaskOut.model_validate(task, from_attributes=True), reused=reused
    )
    return ok(payload.model_dump(mode="json"))


# ------------------------------------------------------------------- shot images
@router.post(
    "/shots/{shot_id}/image/generate",
    summary="生成镜头图片（PRD §22）",
    status_code=201,
)
def generate_shot_image(
    shot_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    images: ImageServiceDep,
    force: Annotated[bool, Query(description="覆盖已有图片（等价 regenerate）")] = False,
) -> dict:
    """Queue one shot's image. Rejects with 409 when the shot already has one."""
    shot = _load_shot(episodes, shot_id, user.id)
    project = _project_of_shot(episodes, user.id, shot)
    task, reused = images.queue_shot_image(shot, project=project, force=force)
    return _accept(task, reused)


@router.post(
    "/shots/{shot_id}/regenerate",
    summary="重新生成镜头素材（PRD §22）",
    status_code=201,
)
def regenerate_shot_media(
    shot_id: uuid.UUID,
    user: CurrentUser,
    episodes: EpisodeServiceDep,
    images: ImageServiceDep,
    kind: Annotated[
        Literal["image", "video", "audio"],
        Query(description="素材类型；Phase 5 只支持 image"),
    ] = "image",
) -> dict:
    """Re-roll a shot's media, keeping the previous asset on disk.

    Section 22 lists one ``regenerate`` route for all media types. Video and audio
    land in Phases 6-7, so asking for them now fails loudly instead of quietly
    generating a picture.
    """
    if kind != "image":
        raise UnsupportedError(f"{kind} 重新生成将在 Phase {'6' if kind == 'video' else '7'} 提供")

    shot = _load_shot(episodes, shot_id, user.id)
    project = _project_of_shot(episodes, user.id, shot)
    task, reused = images.queue_shot_image(shot, project=project, force=True)
    return _accept(task, reused)


@router.post(
    "/episodes/{episode_id}/images/generate",
    summary="批量生成整集镜头图片（➕ 超出 PRD §22）",
    status_code=201,
)
def generate_episode_images(
    episode_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    episodes: EpisodeServiceDep,
    images: ImageServiceDep,
) -> dict:
    """Queue an image for every shot in the episode that lacks one.

    Shots that already have a picture are skipped, not overwritten: this is the
    "fill in what's missing" action, and re-rolling is what ``regenerate`` is for.
    """
    episode = episodes.get_model(user.id, episode_id)
    project = projects.get_model(user, episode.project_id)
    shots = episodes.shots.list_for_episode(episode.id)

    queued: list[dict] = []
    skipped = 0
    for shot in shots:
        if shot.image_asset_id is not None:
            skipped += 1
            continue
        task, reused = images.queue_shot_image(shot, project=project)
        if not reused:
            enqueue_image_task(task.id)
        queued.append(task_out(task))

    return ok(
        {
            "episode_id": str(episode.id),
            "queued": len(queued),
            "skipped_existing": skipped,
            "shots_total": len(shots),
            "tasks": queued,
            "provider": images.provider.name,
            "model": images.provider.model,
        }
    )


# --------------------------------------------------------------- reference images
@router.post(
    "/characters/{character_id}/reference/generate",
    summary="生成人物参考图（➕ 超出 PRD §22，§31 Phase 5 要求）",
    status_code=201,
)
def generate_character_reference(
    character_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    characters: CharacterServiceDep,
    images: ImageServiceDep,
    force: Annotated[bool, Query(description="覆盖已有参考图")] = False,
) -> dict:
    """Queue a reference-sheet image for one character (PRD section 31 Phase 5)."""
    character = characters.get_model(user.id, character_id)
    project = projects.get_model(user, character.project_id)
    task, reused = images.queue_character_reference(character, project=project, force=force)
    return _accept(task, reused)


@router.post(
    "/locations/{location_id}/reference/generate",
    summary="生成场景参考图（➕ 超出 PRD §22，§31 Phase 5 要求）",
    status_code=201,
)
def generate_location_reference(
    location_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    locations: LocationServiceDep,
    images: ImageServiceDep,
    force: Annotated[bool, Query(description="覆盖已有参考图")] = False,
) -> dict:
    """Queue a reference-sheet image for one location (PRD section 31 Phase 5)."""
    location = locations.get_model(user.id, location_id)
    project = projects.get_model(user, location.project_id)
    task, reused = images.queue_location_reference(location, project=project, force=force)
    return _accept(task, reused)


# ------------------------------------------------------------------------ tasks
@router.get("/tasks/{task_id}", summary="生成任务详情（PRD §22）")
def get_task(task_id: uuid.UUID, user: CurrentUser, images: ImageServiceDep) -> dict:
    task = images.tasks.get_for_user(task_id, user.id)
    if task is None:
        raise NotFoundError("生成任务不存在")
    payload = task_out(task)
    # The asset is not in the task row, so resolve it for a client that polls
    # until SUCCESS and then wants the picture in the same response.
    asset = None
    if task.status == TaskStatus.SUCCESS.value and task.shot_id is not None:
        asset = images.assets.latest_for_shots([task.shot_id]).get(task.shot_id)
    payload["asset"] = asset_out(asset)
    return ok(payload)


@router.get("/projects/{project_id}/assets", summary="项目素材列表（➕ 超出 PRD §22）")
def list_project_assets(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    episodes: EpisodeServiceDep,
    images: ImageServiceDep,
    asset_type: Annotated[AssetType | None, Query(description="按素材类型过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict:
    """Every asset the project has produced, newest first.

    Backs the project's 素材 page (PRD section 5.3). Section 22 routes no way to
    read assets back, and until now the only path was per-shot media inside a
    storyboard response -- fine for rendering a board, useless for a gallery.

    SHOT-scoped assets are returned with their shot number and scene so the grid can
    label pictures without a second request per tile; project-level assets (reference
    sheets) carry the entity id instead.
    """
    project = projects.get_model(user, project_id)
    rows = images.assets.list_for_project(project.id, limit=limit)
    if asset_type is not None:
        rows = [row for row in rows if row.type == asset_type.value]

    # One query for the shot labels, rather than one per tile.
    shot_ids = [row.shot_id for row in rows if row.shot_id is not None]
    labels = {
        shot.id: (shot.shot_number, shot.scene_id) for shot in episodes.shots.list_by_ids(shot_ids)
    }

    items = []
    for row in rows:
        payload = asset_out(row) or {}
        label = labels.get(row.shot_id) if row.shot_id is not None else None
        payload["shot_number"] = label[0] if label else None
        payload["scene_id"] = label[1] if label else None
        items.append(payload)

    by_type = {kind.value: sum(1 for row in rows if row.type == kind.value) for kind in AssetType}
    return ok(
        {
            "items": items,
            "totals": {
                "assets": len(items),
                "by_type": by_type,
            },
        }
    )


@router.get("/projects/{project_id}/tasks", summary="项目生成任务列表（PRD §22）")
def list_project_tasks(
    project_id: uuid.UUID,
    user: CurrentUser,
    projects: ProjectServiceDep,
    images: ImageServiceDep,
    task_type: Annotated[TaskType | None, Query(description="按类型过滤")] = None,
    status: Annotated[TaskStatus | None, Query(description="按状态过滤")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    project = projects.get_model(user, project_id)
    items = images.tasks.list_for_project(project.id, limit=limit)
    if task_type is not None:
        items = [item for item in items if item.task_type == task_type.value]
    if status is not None:
        items = [item for item in items if item.status == status.value]

    return ok(
        {
            "items": [task_out(item) for item in items],
            "totals": {
                "tasks": len(items),
                "by_status": {
                    state.value: sum(1 for item in items if item.status == state.value)
                    for state in TaskStatus
                },
            },
        }
    )


@router.post("/tasks/{task_id}/retry", summary="重试失败任务（PRD §22）", status_code=201)
def retry_task(task_id: uuid.UUID, user: CurrentUser, images: ImageServiceDep) -> dict:
    """Re-queue a FAILED task with a fresh retry budget.

    ``SUCCESS`` is refused rather than ignored: silently re-running a finished task
    would spend money again for no new output (``regenerate`` is the explicit way
    to ask for a different picture).
    """
    task = images.tasks.get_for_user(task_id, user.id)
    if task is None:
        raise NotFoundError("生成任务不存在")
    if task.status == TaskStatus.SUCCESS.value:
        raise ConflictError("任务已成功，无需重试；如需换一张请用 regenerate")
    if task.status in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value):
        raise ConflictError("任务正在进行中，请等待完成")

    task.status = TaskStatus.PENDING.value
    task.retry_count = 0
    task.error_message = None
    task.started_at = None
    task.completed_at = None
    images.db.commit()
    enqueue_image_task(task.id)
    payload = TaskAcceptedOut(task=TaskOut.model_validate(task, from_attributes=True))
    return ok(payload.model_dump(mode="json"))


__all__ = ["router", "asset_out", "task_out"]
