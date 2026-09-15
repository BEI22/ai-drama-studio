"""Character + Location Bible services (PRD sections 7, 8, 37 items 14-17).

The PRD requires the user to be able to review and **edit** extracted characters
and locations (section 37 items 17-18), so full CRUD is exposed here rather than
making the Bible read-only agent output.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.character import Character
from app.models.location import Location
from app.models.project import Project
from app.repositories.character import CharacterRepository
from app.repositories.location import LocationRepository
from app.schemas.bible import (
    CharacterCreate,
    CharacterOut,
    CharacterUpdate,
    LocationCreate,
    LocationOut,
    LocationUpdate,
)


class CharacterService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.characters = CharacterRepository(db)

    def list(self, project: Project) -> list[CharacterOut]:
        return [
            CharacterOut.model_validate(row) for row in self.characters.list_for_project(project.id)
        ]

    def get_model(self, user_id: uuid.UUID, character_id: uuid.UUID) -> Character:
        character = self.characters.get_for_user(character_id, user_id)
        if character is None:
            raise NotFoundError("角色不存在")
        return character

    def create(self, project: Project, payload: CharacterCreate) -> CharacterOut:
        if self.characters.get_by_name(project.id, payload.name) is not None:
            raise ConflictError(f"角色「{payload.name}」已存在")

        values = payload.model_dump()
        values["role"] = payload.role.value
        values["sort_order"] = self.characters.next_sort_order(project.id)
        character = self.characters.create(project_id=project.id, **values)
        self.db.commit()
        self.db.refresh(character)
        return CharacterOut.model_validate(character)

    def update(
        self, user_id: uuid.UUID, character_id: uuid.UUID, payload: CharacterUpdate
    ) -> CharacterOut:
        character = self.get_model(user_id, character_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationError("没有需要更新的字段")

        if "name" in changes:
            existing = self.characters.get_by_name(character.project_id, changes["name"])
            if existing is not None and existing.id != character.id:
                raise ConflictError(f"角色「{changes['name']}」已存在")

        for field, value in changes.items():
            if field == "role" and value is not None:
                value = value.value if hasattr(value, "value") else value
            setattr(character, field, value)

        self.db.commit()
        self.db.refresh(character)
        return CharacterOut.model_validate(character)

    def delete(self, user_id: uuid.UUID, character_id: uuid.UUID) -> None:
        character = self.get_model(user_id, character_id)
        self.characters.delete(character)
        self.db.commit()


class LocationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.locations = LocationRepository(db)

    def list(self, project: Project) -> list[LocationOut]:
        return [
            LocationOut.model_validate(row) for row in self.locations.list_for_project(project.id)
        ]

    def get_model(self, user_id: uuid.UUID, location_id: uuid.UUID) -> Location:
        location = self.locations.get_for_user(location_id, user_id)
        if location is None:
            raise NotFoundError("场景不存在")
        return location

    def create(self, project: Project, payload: LocationCreate) -> LocationOut:
        if self.locations.get_by_name(project.id, payload.name) is not None:
            raise ConflictError(f"场景「{payload.name}」已存在")

        values = payload.model_dump()
        values["sort_order"] = self.locations.next_sort_order(project.id)
        location = self.locations.create(project_id=project.id, **values)
        self.db.commit()
        self.db.refresh(location)
        return LocationOut.model_validate(location)

    def update(
        self, user_id: uuid.UUID, location_id: uuid.UUID, payload: LocationUpdate
    ) -> LocationOut:
        location = self.get_model(user_id, location_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationError("没有需要更新的字段")

        if "name" in changes:
            existing = self.locations.get_by_name(location.project_id, changes["name"])
            if existing is not None and existing.id != location.id:
                raise ConflictError(f"场景「{changes['name']}」已存在")

        for field, value in changes.items():
            setattr(location, field, value)

        self.db.commit()
        self.db.refresh(location)
        return LocationOut.model_validate(location)

    def delete(self, user_id: uuid.UUID, location_id: uuid.UUID) -> None:
        location = self.get_model(user_id, location_id)
        self.locations.delete(location)
        self.db.commit()


__all__ = ["CharacterService", "LocationService"]
