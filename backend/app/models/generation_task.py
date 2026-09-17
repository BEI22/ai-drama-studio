"""generation_tasks table (PRD sections 17, 21).

PRD section 21 requires every long-running generation (image, video, TTS,
compose) to be asynchronous:

    POST /generate -> create generation_task -> Redis Queue -> Celery Worker
                   -> Provider -> save Asset -> update Task

with the state machine ``PENDING -> RUNNING -> SUCCESS`` and
``RUNNING -> FAILED -> RETRY``, max 3 retries, and idempotency.

This table is the *durable* half of that contract. The Celery/Redis queue is
volatile -- a Redis flush, a worker restart or a `docker compose down` loses it
-- while the row survives. That is what makes PRD section 32.15 hold ("an
existing successful task is not lost after a restart"): the UI reads task state
from here, and a task stuck in RUNNING with no worker can be retried explicitly.

``idempotency_key`` is ours, not in PRD section 17's column list. PRD section 21
*requires* idempotency but does not say how; the key is what implements it -- a
double-clicked "generate image" on the same shot reuses the live task instead of
paying for a second image. The unique index is partial (only while the task is
live) so that a *finished* task never blocks a deliberate regeneration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import TaskStatus, TaskType

if TYPE_CHECKING:  # pragma: no cover
    from app.models.episode import Episode
    from app.models.project import Project
    from app.models.shot import Shot

# Only one *unfinished* task may exist per idempotency key. Finished tasks
# (SUCCESS/FAILED) drop out of the index, so regenerating is never blocked.
_LIVE_TASK_INDEX_WHERE = text("status IN ('PENDING', 'RUNNING', 'RETRY')")


class GenerationTask(Base):
    __tablename__ = "generation_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
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

    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default=TaskType.IMAGE.value)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TaskStatus.PENDING.value
    )

    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="generation_tasks")
    episode: Mapped[Episode | None] = relationship(back_populates="generation_tasks")
    shot: Mapped[Shot | None] = relationship(back_populates="generation_tasks")

    __table_args__ = (
        # Partial unique index: enforces idempotency without blocking a retry
        # after the previous task finished.
        Index(
            "uq_generation_tasks_live_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=_LIVE_TASK_INDEX_WHERE,
            sqlite_where=_LIVE_TASK_INDEX_WHERE,
        ),
    )
