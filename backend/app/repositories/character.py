"""Character data access.

Like :mod:`app.repositories.project`, every single-entity read is scoped to the
owning user. Characters belong to a project, so ownership requires a join --
there is no unscoped ``get`` exposed to the API layer.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.character import Character
from app.models.project import Project
from app.repositories.base import BaseRepository


class CharacterRepository(BaseRepository[Character]):
    model = Character

    # ---------------------------------------------------------------- scoped reads
    def get_for_user(self, character_id: uuid.UUID, user_id: uuid.UUID) -> Character | None:
        """Fetch a character only if its project belongs to ``user_id``."""
        statement = (
            select(Character)
            .join(Project, Character.project_id == Project.id)
            .where(Character.id == character_id, Project.user_id == user_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_project(self, project_id: uuid.UUID) -> list[Character]:
        statement = (
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.sort_order, Character.created_at)
        )
        return list(self.db.execute(statement).scalars().all())

    def get_by_name(self, project_id: uuid.UUID, name: str) -> Character | None:
        statement = select(Character).where(
            Character.project_id == project_id,
            func.lower(Character.name) == name.strip().lower(),
        )
        return self.db.execute(statement).scalar_one_or_none()

    def count_for_project(self, project_id: uuid.UUID) -> int:
        statement = (
            select(func.count()).select_from(Character).where(Character.project_id == project_id)
        )
        return int(self.db.execute(statement).scalar_one())

    def next_sort_order(self, project_id: uuid.UUID) -> int:
        statement = select(func.max(Character.sort_order)).where(Character.project_id == project_id)
        highest = self.db.execute(statement).scalar_one_or_none()
        return int(highest or 0) + 1

    # -------------------------------------------------------------------- writes
    def create(self, **values) -> Character:
        character = Character(**values)
        self.db.add(character)
        self.db.flush()
        return character
