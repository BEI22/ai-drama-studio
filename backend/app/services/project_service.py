"""Project service -- all Project business rules live here (PRD sections 27, 36).

Ownership rule: every operation takes the acting ``user`` and resolves the
project through ``get_for_user``. A project that does not exist and a project
owned by somebody else are both surfaced as ``NOT_FOUND`` so the API cannot be
used to probe other users' project ids.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.project import Project
from app.models.user import User
from app.repositories.project import ProjectRepository
from app.schemas.project import (
    EpisodeSummary,
    ProjectCreate,
    ProjectDetailOut,
    ProjectListOut,
    ProjectOut,
    ProjectUpdate,
    StorySource,
    StoryUpsert,
)

MAX_PAGE_SIZE = 100


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.projects = ProjectRepository(db)

    # ------------------------------------------------------------- converters
    def _to_out(self, project: Project, episode_count: int) -> ProjectOut:
        return ProjectOut(
            id=project.id,
            name=project.name,
            genre=project.genre,
            style=project.style,
            description=project.description,
            status=project.status,
            story_source=StorySource(project.story_source) if project.story_source else None,
            has_story=bool(project.story_text and project.story_text.strip()),
            episode_count=episode_count,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    def _to_detail(self, project: Project) -> ProjectDetailOut:
        base = self._to_out(project, len(project.episodes))
        return ProjectDetailOut(
            **base.model_dump(),
            story_text=project.story_text,
            story_bible_json=project.story_bible_json,
            episodes=[
                EpisodeSummary.model_validate(episode)
                for episode in sorted(project.episodes, key=lambda item: item.episode_number)
            ],
        )

    # ------------------------------------------------------------------ create
    def create(self, user: User, payload: ProjectCreate) -> ProjectDetailOut:
        project = self.projects.create(
            user_id=user.id,
            name=payload.name,
            genre=payload.genre,
            style=payload.style,
            description=payload.description,
            story_source=payload.story_source.value if payload.story_source else None,
            story_text=payload.story_text,
        )
        self.db.commit()
        self.db.refresh(project)
        return self._to_detail(project)

    # -------------------------------------------------------------------- read
    def list(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> ProjectListOut:
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

        total = self.projects.count_for_user(user.id, search=search, status=status)
        rows = self.projects.list_for_user(
            user.id,
            offset=(page - 1) * page_size,
            limit=page_size,
            search=search,
            status=status,
        )
        counts = self.projects.episode_counts([row.id for row in rows])

        return ProjectListOut(
            items=[self._to_out(row, counts.get(row.id, 0)) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get_model(self, user: User, project_id: uuid.UUID) -> Project:
        project = self.projects.get_for_user(project_id, user.id)
        if project is None:
            raise NotFoundError("项目不存在")
        return project

    def get(self, user: User, project_id: uuid.UUID) -> ProjectDetailOut:
        return self._to_detail(self.get_model(user, project_id))

    # ------------------------------------------------------------------ update
    def update(self, user: User, project_id: uuid.UUID, payload: ProjectUpdate) -> ProjectDetailOut:
        project = self.get_model(user, project_id)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            raise ValidationError("没有需要更新的字段")

        for field, value in changes.items():
            if field == "status" and value is not None:
                value = value.value if hasattr(value, "value") else value
            setattr(project, field, value)

        self.db.commit()
        self.db.refresh(project)
        return self._to_detail(project)

    def delete(self, user: User, project_id: uuid.UUID) -> None:
        project = self.get_model(user, project_id)
        self.projects.delete(project)
        self.db.commit()

    # ------------------------------------------------------------------- story
    def upsert_story(
        self, user: User, project_id: uuid.UUID, payload: StoryUpsert
    ) -> ProjectDetailOut:
        """Save (or replace) the raw story input -- PRD section 36 items 3-4.

        Phase 2 only persists the text. Parsing it into a Story Bible is the
        Story Agent's job in Phase 3.
        """
        project = self.get_model(user, project_id)
        project.story_source = payload.story_source.value
        project.story_text = payload.story_text
        self.db.commit()
        self.db.refresh(project)
        return self._to_detail(project)

    def clear_story(self, user: User, project_id: uuid.UUID) -> ProjectDetailOut:
        project = self.get_model(user, project_id)
        project.story_source = None
        project.story_text = None
        self.db.commit()
        self.db.refresh(project)
        return self._to_detail(project)
