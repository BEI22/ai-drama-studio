"""``episodes`` table (PRD sections 9, 17)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import EpisodeStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project


class Episode(Base, TimestampMixin):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("project_id", "episode_number", name="uq_episodes_project_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, default=180, nullable=False)

    script_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    storyboard_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default=EpisodeStatus.DRAFT.value, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="episodes")
