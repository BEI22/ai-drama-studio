"""Celery application (PRD section 21).

Section 21 fixes the pipeline shape:

    POST /generate -> create generation_task -> Redis Queue -> Celery Worker
                   -> Provider -> save Asset -> update Task

so the broker/backend are Redis (``settings.redis_url`` unless overridden).

``task_always_eager`` is honoured from settings: with it on, ``.delay()`` runs
inline and no worker is needed. That is how the test suite exercises the real
queueing code path without Redis, and how a single-process demo can run. The task
body is written to behave identically either way -- see
``app/services/image_service.py`` for why retries do not use ``self.retry``.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_studio",
    broker=settings.broker_url,
    backend=settings.result_backend,
    include=["app.tasks.image"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # PRD section 21: "必须保证幂等". Combined with the partial unique index on
    # generation_tasks, ack-late delivery can duplicate *messages* without
    # duplicating *work*: the task checks for an existing SUCCESS asset first.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=settings.celery_task_always_eager,
    # A single image generation is bounded by the provider timeout; nothing here
    # should ever run long enough to need the default 1h soft limit.
    task_soft_time_limit=int(settings.image_timeout_seconds * 2 + 60),
    task_time_limit=int(settings.image_timeout_seconds * 3 + 120),
    result_expires=3600,
)

__all__ = ["celery_app"]
