"""Media schemas (PRD sections 17, 21, 22, 25 -- Phase 5).

Response models for Assets and generation tasks. Request models are deliberately
tiny: the server decides the prompt, the provider and the storage key, so a client
only says *what* to generate (a shot, a character reference, a location reference)
and *whether* overwriting is intended.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import AssetType, TaskStatus, TaskType


class AssetOut(BaseModel):
    """One stored file (PRD section 17 ``assets`` / section 25)."""

    id: uuid.UUID
    project_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    shot_id: uuid.UUID | None = None
    type: AssetType
    # ``url`` is a signed, expiring link (PRD section 27); ``storage_key`` is the
    # durable identity of the file.
    url: str | None = None
    storage_key: str
    duration: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")
    created_at: datetime

    model_config = {"populate_by_name": True, "from_attributes": True}


class TaskOut(BaseModel):
    """One async generation task (PRD sections 17, 21).

    ``status`` follows section 21 exactly: PENDING -> RUNNING -> SUCCESS, or
    RUNNING -> RETRY -> ... -> FAILED. The UI polls this row.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    episode_id: uuid.UUID | None = None
    shot_id: uuid.UUID | None = None
    task_type: TaskType
    status: TaskStatus
    provider: str | None = None
    model: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    estimated_cost: float | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("input_payload", "output_payload", mode="before")
    @classmethod
    def _none_to_empty_dict(cls, value: Any) -> Any:
        # Both columns are nullable JSON and are None until the task reaches the
        # stage that fills them (output_payload only exists after success), so a
        # bare ``dict`` would reject every freshly created task.
        return value or {}


class ShotImageOut(BaseModel):
    """The image state of one shot, as the storyboard UI needs it.

    Returned per shot so one request can render the whole storyboard: the newest
    asset (if any), how many attempts produced pictures, and the task to poll
    while one is in flight.
    """

    shot_id: uuid.UUID
    shot_number: int
    scene_id: str
    status: str
    image_asset_id: uuid.UUID | None = None
    asset: AssetOut | None = None
    image_count: int = 0
    latest_task: TaskOut | None = None


class EpisodeImageStatusOut(BaseModel):
    """Per-episode rollup of the image pipeline."""

    episode_id: uuid.UUID
    shots_total: int
    shots_with_image: int
    tasks_pending: int
    tasks_running: int
    tasks_failed: int
    provider: str
    model: str


class TaskAcceptedOut(BaseModel):
    """Response of every generate/regenerate endpoint (202-style accept).

    ``reused=True`` means an identical task was already in flight and was handed
    back instead of queueing a second one -- PRD section 21's idempotency made
    visible, so a double-click is observably harmless rather than silently costly.
    """

    task: TaskOut
    reused: bool = False


__all__ = [
    "AssetOut",
    "EpisodeImageStatusOut",
    "ShotImageOut",
    "TaskAcceptedOut",
    "TaskOut",
]
