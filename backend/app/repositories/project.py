"""Project data access.

Security note (PRD section 27): *every* read path is ownership-scoped. The public
API deliberately exposes ``get_for_user`` rather than an unscoped ``get`` so a
caller cannot forget the ``user_id`` filter.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select

from app.models.episode import Episode
from app.models.project import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    # ------------------------------------------------------------------ reads
    def get_for_user(self, project_id: uuid.UUID, user_id: uuid.UUID) -> Project | None:
        """Fetch a project only if it belongs to ``user_id``.

        Returns ``None`` both when the project does not exist and when it belongs
        to somebody else, so the API cannot be used to enumerate other users'
        project ids.
        """
        statement = select(Project).where(
            Project.id == project_id,
            Project.user_id == user_id,
        )
        return self.db.execute(statement).scalar_one_or_none()

    def _filtered(
        self,
        user_id: uuid.UUID,
        *,
        search: str | None = None,
        status: str | None = None,
    ) -> Select:
        statement = select(Project).where(Project.user_id == user_id)
        if search:
            statement = statement.where(Project.name.ilike(f"%{search.strip()}%"))
        if status:
            statement = statement.where(Project.status == status)
        return statement

    def count_for_user(
        self,
        user_id: uuid.UUID,
        *,
        search: str | None = None,
        status: str | None = None,
    ) -> int:
        statement = self._filtered(user_id, search=search, status=status)
        count_statement = select(func.count()).select_from(statement.subquery())
        return int(self.db.execute(count_statement).scalar_one())

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> list[Project]:
        statement = (
            self._filtered(user_id, search=search, status=status)
            .order_by(Project.updated_at.desc(), Project.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())

    def episode_count(self, project_id: uuid.UUID) -> int:
        statement = (
            select(func.count()).select_from(Episode).where(Episode.project_id == project_id)
        )
        return int(self.db.execute(statement).scalar_one())

    def episode_counts(self, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Batch episode counts for a page of projects (avoids N+1)."""
        if not project_ids:
            return {}
        statement = (
            select(Episode.project_id, func.count(Episode.id))
            .where(Episode.project_id.in_(project_ids))
            .group_by(Episode.project_id)
        )
        return {row[0]: int(row[1]) for row in self.db.execute(statement).all()}

    # ----------------------------------------------------------------- writes
    def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        genre: str | None = None,
        style: str | None = None,
        description: str | None = None,
        story_source: str | None = None,
        story_text: str | None = None,
    ) -> Project:
        project = Project(
            user_id=user_id,
            name=name.strip(),
            genre=genre,
            style=style,
            description=description,
            story_source=story_source,
            story_text=story_text,
        )
        self.db.add(project)
        self.db.flush()
        return project
