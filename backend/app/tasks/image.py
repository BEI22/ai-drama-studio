"""Image generation Celery task (PRD section 21).

Thin by design: it owns only a session and delegates to ``ImageService``. All the
business rules -- idempotency, retry accounting, the state machine, storage,
Asset creation -- live in the service, so the same code runs under a real worker
and under ``CELERY_TASK_ALWAYS_EAGER=true`` (tests, single-process demo). A task
that reimplemented those rules would drift from the eager path, and then "tests
pass, worker behaves differently" becomes possible.

Note the task never raises on a generation failure: the failure is *recorded* on
the generation_task row (PRD section 21's RUNNING -> FAILED -> RETRY), which is
what the UI polls. Raising would only mark the Celery result as failed while the
database said nothing at all.
"""

from __future__ import annotations

import logging
import uuid

from app.core.database import SessionLocal
from app.services.image_service import ImageService
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="image.generate", bind=True, max_retries=0)
def generate_image_task(self, task_id: str) -> dict[str, str]:
    """Run one queued image generation to completion."""
    parsed = uuid.UUID(str(task_id))
    db = SessionLocal()
    try:
        task = ImageService(db).execute_task(parsed)
        logger.info(
            "image task %s finished with status=%s retries=%s",
            task_id,
            task.status,
            task.retry_count,
        )
        return {"task_id": str(task.id), "status": task.status}
    finally:
        db.close()


__all__ = ["generate_image_task"]
