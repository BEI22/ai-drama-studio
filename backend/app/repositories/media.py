"""Asset + generation-task data access (PRD sections 17, 21, 25).

Same rule as every other repository here (PRD section 27): reads are
ownership-scoped, so a route cannot forget the filter and leak another user's
generated files. There is no unscoped ``get`` for either model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.asset import Asset
from app.models.episode import Episode
from app.models.generation_task import GenerationTask
from app.models.project import Project
from app.models.shot import Shot
from app.models.user import User
from app.repositories.base import BaseRepository

# A task is "live" while it may still be running. Only one live task may exist
# per idempotency key (see the partial unique index in migration 0005).
LIVE_STATUSES = ("PENDING", "RUNNING", "RETRY")


class AssetRepository(BaseRepository[Asset]):
    model = Asset

    # ------------------------------------------------------------- scoped reads
    def get_for_user(self, asset_id: uuid.UUID, user_id: uuid.UUID) -> Asset | None:
        statement = (
            select(Asset)
            .join(Project, Asset.project_id == Project.id)
            .where(Asset.id == asset_id, Project.user_id == user_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_project(self, project_id: uuid.UUID, *, limit: int = 200) -> list[Asset]:
        statement = (
            select(Asset)
            .where(Asset.project_id == project_id)
            .order_by(Asset.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())

    def latest_for_shots(self, shot_ids: list[uuid.UUID]) -> dict[uuid.UUID, Asset]:
        """Newest asset per shot, in one query (avoids N+1 in the storyboard view).

        "Newest" and not "the row the shot points at": regeneration appends, so
        the newest row is the current picture while earlier ones stay on disk.
        """
        if not shot_ids:
            return {}
        statement = (
            select(Asset)
            .where(Asset.shot_id.in_(shot_ids))
            .order_by(Asset.shot_id, Asset.created_at)
        )
        newest: dict[uuid.UUID, Asset] = {}
        for asset in self.db.execute(statement).scalars().all():
            if asset.shot_id is not None:
                newest[asset.shot_id] = asset  # later rows overwrite earlier ones
        return newest

    def image_counts_for_shots(self, shot_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not shot_ids:
            return {}
        statement = (
            select(Asset.shot_id, func.count(Asset.id))
            .where(Asset.shot_id.in_(shot_ids))
            .group_by(Asset.shot_id)
        )
        return {row[0]: int(row[1]) for row in self.db.execute(statement).all() if row[0]}

    # ------------------------------------------------------------------- writes
    def create(self, **values) -> Asset:
        asset = Asset(**values)
        self.db.add(asset)
        self.db.flush()
        return asset


class GenerationTaskRepository(BaseRepository[GenerationTask]):
    model = GenerationTask

    # ------------------------------------------------------------- scoped reads
    def get_for_user(self, task_id: uuid.UUID, user_id: uuid.UUID) -> GenerationTask | None:
        statement = (
            select(GenerationTask)
            .join(Project, GenerationTask.project_id == Project.id)
            .where(GenerationTask.id == task_id, Project.user_id == user_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_project(self, project_id: uuid.UUID, *, limit: int = 100) -> list[GenerationTask]:
        statement = (
            select(GenerationTask)
            .where(GenerationTask.project_id == project_id)
            .order_by(GenerationTask.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(statement).scalars().all())

    def find_live_by_key(self, idempotency_key: str) -> GenerationTask | None:
        """The unfinished task for this key, if any -- the idempotency lookup."""
        statement = select(GenerationTask).where(
            GenerationTask.idempotency_key == idempotency_key,
            GenerationTask.status.in_(LIVE_STATUSES),
        )
        return self.db.execute(statement).scalar_one_or_none()

    def latest_for_shot(self, shot_id: uuid.UUID) -> GenerationTask | None:
        statement = (
            select(GenerationTask)
            .where(GenerationTask.shot_id == shot_id)
            .order_by(GenerationTask.created_at.desc())
            .limit(1)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def latest_task_ids_for_shots(self, shot_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        """Newest task id per shot -- lets the UI poll without a second request."""
        if not shot_ids:
            return {}
        statement = (
            select(GenerationTask)
            .where(GenerationTask.shot_id.in_(shot_ids))
            .order_by(GenerationTask.shot_id, GenerationTask.created_at)
        )
        newest: dict[uuid.UUID, uuid.UUID] = {}
        for task in self.db.execute(statement).scalars().all():
            if task.shot_id is not None:
                newest[task.shot_id] = task.id
        return newest

    def owner_id(self, task_id: uuid.UUID) -> uuid.UUID | None:
        """The user that owns a task's project -- used by the worker, which has
        no request context and therefore no ``CurrentUser``."""
        statement = (
            select(User.id)
            .select_from(GenerationTask)
            .join(Project, GenerationTask.project_id == Project.id)
            .join(User, Project.user_id == User.id)
            .where(GenerationTask.id == task_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def project_id_of_shot(self, shot_id: uuid.UUID) -> uuid.UUID | None:
        statement = (
            select(Project.id)
            .select_from(Shot)
            .join(Episode, Shot.episode_id == Episode.id)
            .join(Project, Episode.project_id == Project.id)
            .where(Shot.id == shot_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    # ------------------------------------------------------------------- writes
    def create(self, **values) -> GenerationTask:
        task = GenerationTask(**values)
        self.db.add(task)
        self.db.flush()
        return task


__all__ = ["LIVE_STATUSES", "AssetRepository", "GenerationTaskRepository"]
