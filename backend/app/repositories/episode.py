"""Episode + Shot data access.

Like every other repository here (PRD section 27), single-entity reads are
ownership-scoped: episodes belong to a project which belongs to a user, so
ownership needs a join. There is deliberately no unscoped ``get`` exposed to the
API layer, so a route cannot forget the filter.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.episode import Episode
from app.models.project import Project
from app.models.shot import Shot
from app.repositories.base import BaseRepository


class EpisodeRepository(BaseRepository[Episode]):
    model = Episode

    # ---------------------------------------------------------------- scoped reads
    def get_for_user(self, episode_id: uuid.UUID, user_id: uuid.UUID) -> Episode | None:
        """Fetch an episode only if its project belongs to ``user_id``."""
        statement = (
            select(Episode)
            .join(Project, Episode.project_id == Project.id)
            .where(Episode.id == episode_id, Project.user_id == user_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_project(self, project_id: uuid.UUID) -> list[Episode]:
        statement = (
            select(Episode).where(Episode.project_id == project_id).order_by(Episode.episode_number)
        )
        return list(self.db.execute(statement).scalars().all())

    def get_by_number(self, project_id: uuid.UUID, episode_number: int) -> Episode | None:
        statement = select(Episode).where(
            Episode.project_id == project_id,
            Episode.episode_number == episode_number,
        )
        return self.db.execute(statement).scalar_one_or_none()

    def count_for_project(self, project_id: uuid.UUID) -> int:
        statement = (
            select(func.count()).select_from(Episode).where(Episode.project_id == project_id)
        )
        return int(self.db.execute(statement).scalar_one())

    def next_episode_number(self, project_id: uuid.UUID) -> int:
        statement = select(func.max(Episode.episode_number)).where(Episode.project_id == project_id)
        highest = self.db.execute(statement).scalar_one_or_none()
        return int(highest or 0) + 1

    def shot_counts(self, episode_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Batch shot counts for a list of episodes (avoids N+1)."""
        if not episode_ids:
            return {}
        statement = (
            select(Shot.episode_id, func.count(Shot.id))
            .where(Shot.episode_id.in_(episode_ids))
            .group_by(Shot.episode_id)
        )
        return {row[0]: int(row[1]) for row in self.db.execute(statement).all()}

    # -------------------------------------------------------------------- writes
    def create(self, **values) -> Episode:
        episode = Episode(**values)
        self.db.add(episode)
        self.db.flush()
        return episode

    def delete_for_project(self, project_id: uuid.UUID) -> int:
        """Remove every episode of a project (shots cascade). Returns the count."""
        rows = self.list_for_project(project_id)
        for row in rows:
            self.db.delete(row)
        self.db.flush()
        return len(rows)


class ShotRepository(BaseRepository[Shot]):
    model = Shot

    # ---------------------------------------------------------------- scoped reads
    def get_for_user(self, shot_id: uuid.UUID, user_id: uuid.UUID) -> Shot | None:
        statement = (
            select(Shot)
            .join(Episode, Shot.episode_id == Episode.id)
            .join(Project, Episode.project_id == Project.id)
            .where(Shot.id == shot_id, Project.user_id == user_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_episode(self, episode_id: uuid.UUID) -> list[Shot]:
        """Ordered by the absolute ``sequence``, not per-scene ``shot_number``.

        ``shot_number`` restarts at 1 in each scene, so ordering by it alone
        would interleave scenes.
        """
        statement = (
            select(Shot)
            .where(Shot.episode_id == episode_id)
            .order_by(Shot.sequence, Shot.shot_number)
        )
        return list(self.db.execute(statement).scalars().all())

    def count_for_episode(self, episode_id: uuid.UUID) -> int:
        statement = select(func.count()).select_from(Shot).where(Shot.episode_id == episode_id)
        return int(self.db.execute(statement).scalar_one())

    def delete_for_episode(self, episode_id: uuid.UUID) -> int:
        rows = self.list_for_episode(episode_id)
        for row in rows:
            self.db.delete(row)
        self.db.flush()
        return len(rows)

    # -------------------------------------------------------------------- writes
    def create(self, **values) -> Shot:
        shot = Shot(**values)
        self.db.add(shot)
        self.db.flush()
        return shot


__all__ = ["EpisodeRepository", "ShotRepository"]
