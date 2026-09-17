"""Asset table (PRD sections 17, 25).

Every generated file -- reference images, shot images, and later video/audio --
gets exactly one row here. PRD section 25 is explicit that the database stores
only ``storage_key`` / ``url`` / ``metadata`` and that the bytes live on disk (or
S3/OSS), never in PostgreSQL.

``metadata_json`` carries the provider's own report (model, size, seed, cost,
latency). Keeping it as JSON rather than columns means a new provider attribute
never forces a migration -- the same reasoning as ``projects.story_bible_json``.

Only ``created_at`` is defined here; PRD section 17's assets table has no
``updated_at``, and an asset is immutable once written: regenerating a shot
creates a *new* row, which is what makes "a failed shot can be regenerated"
(PRD section 32.14) and "an existing success is never lost" (32.15) both true.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AssetType

if TYPE_CHECKING:  # pragma: no cover
    from app.models.episode import Episode
    from app.models.project import Project
    from app.models.shot import Shot


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Nullable: a character/location reference image belongs to a project only.
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    shot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("shots.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False, default=AssetType.IMAGE.value)

    # Path relative to the storage root, e.g. "project/<pid>/shots/<sid>.png".
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Public (signed, expiring) URL. Recomputed on read -- see app/core/signing.py.
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="assets")
    episode: Mapped[Episode | None] = relationship(back_populates="assets")
    shot: Mapped[Shot | None] = relationship(back_populates="assets")
