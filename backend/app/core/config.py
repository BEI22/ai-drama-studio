"""Application settings.

All configuration comes from environment variables (optionally loaded from a
``.env`` file). No secret ever lives in source code -- see ``.env.example``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime configuration for the AI Studio backend."""

    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- application -----------------------------------------------------
    app_name: str = "AI Studio"
    app_version: str = "0.1.0"
    environment: str = "local"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # --- security --------------------------------------------------------
    secret_key: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # --- database --------------------------------------------------------
    database_url: str = "postgresql+psycopg://ai_studio:ai_studio@localhost:5432/ai_studio"
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # --- cache / queue ---------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_task_max_retries: int = 3
    celery_task_always_eager: bool = False

    # --- storage ---------------------------------------------------------
    storage_backend: str = "local"
    storage_local_dir: str = str(REPO_DIR / "storage")
    storage_public_base_url: str = "http://localhost:8000/static"

    # --- providers (Phase 3 wires up LLM; media providers stay mock) ------
    llm_provider: str = "mock"
    image_provider: str = "mock"
    video_provider: str = "mock"
    tts_provider: str = "mock"

    # OpenAI-compatible LLM endpoint (used when llm_provider != "mock").
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 3
    llm_temperature: float = 0.4

    # Mock provider behaviour. ``mock_llm_fail_times`` makes the first N calls
    # fail so the retry path can be exercised in tests and demos.
    mock_llm_fail_times: int = 0
    mock_llm_latency_ms: int = 0

    # --- http ------------------------------------------------------------
    # NoDecode: pydantic-settings would otherwise try to JSON-decode this list
    # field straight from .env and fail on `http://a,http://b`; the validator
    # below owns the parsing instead.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    request_id_header: str = "X-Request-ID"

    # --- logging ---------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: Any) -> Any:
        """Accept a JSON list, a comma-separated string, or a real list.

        Note: validators run before pydantic-settings' JSON decoding when values
        are injected programmatically, so JSON strings are parsed here too.
        """
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("["):
                try:
                    return json.loads(raw)
                except ValueError as exc:  # pragma: no cover - malformed env var
                    raise ValueError(f"CORS_ORIGINS is not valid JSON: {raw!r}") from exc
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value

    # --- derived ---------------------------------------------------------
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (import-safe, test-overridable via env vars)."""
    return Settings()


settings = get_settings()
