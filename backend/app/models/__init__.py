"""ORM models.

Importing this package registers every table on ``Base.metadata`` -- Alembic
autogenerate and ``create_all`` both rely on that.
"""

from app.core.database import Base, TimestampMixin
from app.models.character import Character
from app.models.enums import (
    AnalysisStatus,
    AssetType,
    CameraMovement,
    CharacterRole,
    EpisodeStatus,
    MemoryType,
    ProjectStatus,
    ShotSize,
    ShotStatus,
    TaskStatus,
    TaskType,
)
from app.models.episode import Episode
from app.models.location import Location
from app.models.project import Project
from app.models.shot import Shot
from app.models.user import User

__all__ = [
    "AnalysisStatus",
    "AssetType",
    "Base",
    "CameraMovement",
    "Character",
    "CharacterRole",
    "Episode",
    "EpisodeStatus",
    "Location",
    "MemoryType",
    "Project",
    "ProjectStatus",
    "Shot",
    "ShotSize",
    "ShotStatus",
    "TaskStatus",
    "TaskType",
    "TimestampMixin",
    "User",
]
