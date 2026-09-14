"""Health check payloads (PRD section 31)."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Bare contract required by the PRD and used by Docker healthchecks."""

    status: str = "ok"


class ComponentHealth(BaseModel):
    name: str
    status: str
    detail: str | None = None
    latency_ms: float | None = None


class HealthDetailResponse(BaseModel):
    status: str
    version: str
    environment: str
    components: list[ComponentHealth]
