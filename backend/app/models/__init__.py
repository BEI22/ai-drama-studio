"""ORM models.

Importing this package registers every table on ``Base.metadata`` -- Alembic
autogenerate and ``create_all`` both rely on that.
"""

from app.core.database import Base, TimestampMixin
from app.models.enums import (
    AssetType,
    EpisodeStatus,
    MemoryType,
    ProjectStatus,
    TaskStatus,
    TaskType,
)
from app.models.episode import Episode
from app.models.project import Project
from app.models.user import User

__all__ = [
    "AssetType",
    "Base",
    "Episode",
    "EpisodeStatus",
    "MemoryType",
    "Project",
    "ProjectStatus",
    "TaskStatus",
    "TaskType",
    "TimestampMixin",
    "User",
]
