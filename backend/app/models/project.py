"""``projects`` table (PRD section 17)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import ProjectStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.episode import Episode
    from app.models.user import User


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured Story Bible (PRD section 6). Never free-form text.
    story_bible_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default=ProjectStatus.DRAFT.value, nullable=False
    )

    user: Mapped[User] = relationship(back_populates="projects")
    episodes: Mapped[list[Episode]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Episode.episode_number",
    )
