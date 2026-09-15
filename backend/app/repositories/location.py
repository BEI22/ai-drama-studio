"""Location data access -- same ownership discipline as characters."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.location import Location
from app.models.project import Project
from app.repositories.base import BaseRepository


class LocationRepository(BaseRepository[Location]):
    model = Location

    def get_for_user(self, location_id: uuid.UUID, user_id: uuid.UUID) -> Location | None:
        statement = (
            select(Location)
            .join(Project, Location.project_id == Project.id)
            .where(Location.id == location_id, Project.user_id == user_id)
        )
        return self.db.execute(statement).scalar_one_or_none()

    def list_for_project(self, project_id: uuid.UUID) -> list[Location]:
        statement = (
            select(Location)
            .where(Location.project_id == project_id)
            .order_by(Location.sort_order, Location.created_at)
        )
        return list(self.db.execute(statement).scalars().all())

    def get_by_name(self, project_id: uuid.UUID, name: str) -> Location | None:
        statement = select(Location).where(
            Location.project_id == project_id,
            func.lower(Location.name) == name.strip().lower(),
        )
        return self.db.execute(statement).scalar_one_or_none()

    def count_for_project(self, project_id: uuid.UUID) -> int:
        statement = (
            select(func.count()).select_from(Location).where(Location.project_id == project_id)
        )
        return int(self.db.execute(statement).scalar_one())

    def next_sort_order(self, project_id: uuid.UUID) -> int:
        statement = select(func.max(Location.sort_order)).where(Location.project_id == project_id)
        highest = self.db.execute(statement).scalar_one_or_none()
        return int(highest or 0) + 1

    def create(self, **values) -> Location:
        location = Location(**values)
        self.db.add(location)
        self.db.flush()
        return location
