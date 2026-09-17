"""``shots`` table (PRD sections 11, 17).

PRD section 17 defines this table; section 11 defines the storyboard JSON that
produces it. Rows exist so Phases 5-7 can attach generated media to a specific
shot (``image_asset_id`` / ``video_asset_id`` / ``audio_asset_id``) and so a user
can regenerate one shot without re-running the whole episode.

Two shape notes, both deliberate:

* ``scene_id`` is a **string**, not a foreign key. Script scenes live inside
  ``episodes.script_json`` (PRD section 10) rather than in their own table, so
  the scene identifier is the label the script uses ("S1", "S2"...). Adding a
  ``scenes`` table would duplicate data the script already owns.
* ``characters_json`` holds character **names**, matching section 11's
  ``characters: []``. The script binds real ``character_id``s (that is where
  PRD section 10 demands it); the storyboard is written for humans to read, and
  the API response resolves names back to ids for callers that need them.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.models.enums import ShotStatus

if TYPE_CHECKING:  # pragma: no cover
    from app.models.asset import Asset
    from app.models.episode import Episode
    from app.models.generation_task import GenerationTask


class Shot(Base, TimestampMixin):
    __tablename__ = "shots"
    __table_args__ = (
        # PRD section 11 numbers shots *within* a scene, so each scene restarts
        # at 1 -- the constraint has to include scene_id or a multi-scene
        # storyboard would collide on the second scene.
        UniqueConstraint(
            "episode_id", "scene_id", "shot_number", name="uq_shots_episode_scene_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("episodes.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Script scene label ("S1"), unique per episode but not a table of its own.
    scene_id: Mapped[str] = mapped_column(String(64), nullable=False)
    shot_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Absolute order across the whole episode. ``shot_number`` restarts per
    # scene, which is right for display but wrong for composition (Phase 8),
    # which needs one deterministic sequence.
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    duration: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    shot_size: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    camera_movement: Mapped[str] = mapped_column(String(32), default="static", nullable=False)

    characters_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # PRD section 19: the composed prompts that later phases consume.
    image_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Phases 5-7 fill these in; declared now so the column set stops churning.
    image_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    video_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    audio_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default=ShotStatus.DRAFT.value, nullable=False)

    episode: Mapped[Episode] = relationship(back_populates="shots")
    # Phase 5+: media hangs off the shot. A shot accumulates one asset per
    # attempt, so the newest successful image is the one to render -- and an
    # earlier success is never destroyed by a later failure.
    assets: Mapped[list[Asset]] = relationship(
        back_populates="shot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Asset.created_at",
    )
    generation_tasks: Mapped[list[GenerationTask]] = relationship(
        back_populates="shot",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
