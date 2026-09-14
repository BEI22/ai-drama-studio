"""Project + Story routes (PRD sections 22, 36).

Mounted under the versioned prefix, so PRD section 22's logical paths map as::

    POST   /api/projects                      -> POST   /api/v1/projects
    GET    /api/projects                      -> GET    /api/v1/projects
    GET    /api/projects/{id}                 -> GET    /api/v1/projects/{id}
    PATCH  /api/projects/{id}                 -> PATCH  /api/v1/projects/{id}
    DELETE /api/projects/{id}                 -> DELETE /api/v1/projects/{id}
    POST   /api/projects/{id}/story           -> POST   /api/v1/projects/{id}/story

``POST /projects/{id}/analyze`` and ``GET /projects/{id}/bible`` are Phase 3
(Story Agent) and are intentionally absent.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, ProjectServiceDep
from app.core.responses import ok
from app.models.enums import ProjectStatus
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    StorySource,
    StoryUpsert,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", status_code=status.HTTP_201_CREATED, summary="创建项目")
def create_project(payload: ProjectCreate, user: CurrentUser, service: ProjectServiceDep) -> dict:
    project = service.create(user, payload)
    logger.info(
        "project created",
        extra={"project_id": str(project.id), "user_id": str(user.id)},
    )
    return ok(project.model_dump(mode="json"))


@router.get("", summary="项目列表（分页 / 搜索 / 按状态筛选）")
def list_projects(
    user: CurrentUser,
    service: ProjectServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, max_length=200, description="按项目名称模糊搜索"),
    project_status: ProjectStatus | None = Query(default=None, alias="status"),
) -> dict:
    result = service.list(
        user,
        page=page,
        page_size=page_size,
        search=search,
        status=project_status.value if project_status else None,
    )
    return ok(
        {"items": [item.model_dump(mode="json") for item in result.items]},
        meta={
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "pages": (result.total + result.page_size - 1) // result.page_size,
        },
    )


@router.get("/{project_id}", summary="项目详情")
def get_project(project_id: uuid.UUID, user: CurrentUser, service: ProjectServiceDep) -> dict:
    return ok(service.get(user, project_id).model_dump(mode="json"))


@router.patch("/{project_id}", summary="更新项目")
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: CurrentUser,
    service: ProjectServiceDep,
) -> dict:
    project = service.update(user, project_id, payload)
    logger.info("project updated", extra={"project_id": str(project_id)})
    return ok(project.model_dump(mode="json"))


@router.delete("/{project_id}", status_code=status.HTTP_200_OK, summary="删除项目")
def delete_project(project_id: uuid.UUID, user: CurrentUser, service: ProjectServiceDep) -> dict:
    service.delete(user, project_id)
    logger.info("project deleted", extra={"project_id": str(project_id)})
    return ok({"id": str(project_id), "deleted": True})


# ----------------------------------------------------------------------- story
@router.post("/{project_id}/story", summary="保存 / 替换故事文本")
def upsert_story(
    project_id: uuid.UUID,
    payload: StoryUpsert,
    user: CurrentUser,
    service: ProjectServiceDep,
) -> dict:
    """Phase 2 persists the raw story only -- no AI parsing yet (PRD section 36)."""
    project = service.upsert_story(user, project_id, payload)
    logger.info(
        "story saved",
        extra={"project_id": str(project_id), "chars": len(payload.story_text)},
    )
    return ok(project.model_dump(mode="json"))


@router.get("/{project_id}/story", summary="读取已保存的故事文本")
def get_story(project_id: uuid.UUID, user: CurrentUser, service: ProjectServiceDep) -> dict:
    project = service.get(user, project_id)
    return ok(
        {
            "story_source": project.story_source.value if project.story_source else None,
            "story_text": project.story_text,
            "has_story": project.has_story,
        }
    )


@router.delete("/{project_id}/story", summary="清空故事文本")
def clear_story(project_id: uuid.UUID, user: CurrentUser, service: ProjectServiceDep) -> dict:
    project = service.clear_story(user, project_id)
    return ok({"id": str(project.id), "has_story": project.has_story})


# Re-exported for docs/tests convenience.
__all__ = ["router", "StorySource"]
