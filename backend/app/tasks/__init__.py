"""Queue dispatch helpers.

Keeps Celery out of the API layer: a route calls ``enqueue_image_task`` and does
not care whether the work is published to Redis or executed inline. That is what
makes ``CELERY_TASK_ALWAYS_EAGER=true`` a working configuration rather than a
special case -- the same route code drives both (PRD section 21).
"""

from __future__ import annotations

import uuid


def enqueue_image_task(task_id: uuid.UUID | str) -> None:
    """Publish an image generation task (fire and forget)."""
    from app.tasks.image import generate_image_task

    generate_image_task.delay(str(task_id))


__all__ = ["enqueue_image_task"]
