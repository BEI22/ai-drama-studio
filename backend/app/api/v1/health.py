"""Health endpoints.

* ``GET /health``            -- bare liveness probe, exact PRD section 31 contract.
* ``GET /api/v1/health``     -- readiness probe with dependency checks, wrapped in
  the unified response envelope.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import settings
from app.core.responses import ok
from app.schemas.health import ComponentHealth, HealthDetailResponse, HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def check_database(db: DbSession) -> ComponentHealth:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - health checks must never raise
        logger.warning("database health check failed: %s", exc)
        return ComponentHealth(name="database", status="down", detail=str(exc))
    latency = round((time.perf_counter() - started) * 1000, 2)
    return ComponentHealth(name="database", status="up", latency_ms=latency)


def check_redis() -> ComponentHealth:
    """Ping Redis if the client library is importable and reachable."""
    started = time.perf_counter()
    try:
        import redis  # imported lazily so the API runs without Redis installed
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        return ComponentHealth(name="redis", status="unknown", detail=str(exc))

    try:
        client = redis.Redis.from_url(
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis health check failed: %s", exc)
        return ComponentHealth(name="redis", status="down", detail=str(exc))
    latency = round((time.perf_counter() - started) * 1000, 2)
    return ComponentHealth(name="redis", status="up", latency_ms=latency)


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Liveness: the process is up and serving requests."""
    return HealthResponse(status="ok")


@router.get("/health/detail", summary="Readiness probe with dependency checks")
def health_detail(db: DbSession) -> dict:
    """Readiness: report the status of every external dependency."""
    components = [check_database(db), check_redis()]
    overall = "ok" if all(component.status == "up" for component in components) else "degraded"
    payload = HealthDetailResponse(
        status=overall,
        version=settings.app_version,
        environment=settings.environment,
        components=components,
    )
    return ok(payload.model_dump())
