"""``episodes`` table (PRD sections 9, 17)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import EpisodeStatus, GenerationStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.asset import Asset
    from app.models.generation_task import GenerationTask
    from app.models.project import Project
    from app.models.shot import Shot


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

    # Per-step run state. Kept alongside the JSON so "generated but empty" and
    # "failed" are distinguishable, and a failure keeps a readable error (the
    # same reasoning as ``Project.analysis_status``).
    script_status: Mapped[str] = mapped_column(
        String(32), default=GenerationStatus.NOT_GENERATED.value, nullable=False
    )
    storyboard_status: Mapped[str] = mapped_column(
        String(32), default=GenerationStatus.NOT_GENERATED.value, nullable=False
    )
    generation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    storyboard_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(32), default=EpisodeStatus.DRAFT.value, nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="episodes")
    shots: Mapped[list[Shot]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Shot.shot_number",
    )
    # Phase 5: assets are attached to the episode that produced them (shot
    # images), and the task log is per episode so the UI can show progress.
    assets: Mapped[list[Asset]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    generation_tasks: Mapped[list[GenerationTask]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
