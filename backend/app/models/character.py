"""Character Bible table (PRD sections 7, 17).

Column set is the union of PRD section 17's ``characters`` table and the
Character Bible JSON in section 7 -- section 17 lists the storage shape, section
7 the semantic fields. ``sort_order`` is ours, to keep AI-extracted order stable
in the UI.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import CharacterRole

if TYPE_CHECKING:  # pragma: no cover
    from app.models.project import Project


class Character(Base, TimestampMixin):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(
        String(32), default=CharacterRole.SUPPORTING.value, nullable=False
    )
    age: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # One-line summary vs. the visual description fed into image prompts later.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance: Mapped[str | None] = mapped_column(Text, nullable=True)
    hair: Mapped[str | None] = mapped_column(String(200), nullable=True)
    clothing: Mapped[str | None] = mapped_column(Text, nullable=True)

    personality: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Phase 7 (TTS) / Phase 5 (image reference) -- persisted now so the schema
    # does not churn again.
    voice_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    project: Mapped[Project] = relationship(back_populates="characters")
