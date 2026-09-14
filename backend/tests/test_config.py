"""Settings behaviour (PRD section 29, ``.env.example``)."""

from __future__ import annotations

import pytest

from app.core.config import Settings, settings


def test_test_run_uses_sqlite() -> None:
    assert settings.is_sqlite
    assert settings.environment == "test"


def test_cors_origins_accept_comma_separated_string() -> None:
    configured = Settings(cors_origins="http://a.test, http://b.test")
    assert configured.cors_origins == ["http://a.test", "http://b.test"]


def test_cors_origins_accept_json_list() -> None:
    configured = Settings(cors_origins='["http://c.test"]')
    assert configured.cors_origins == ["http://c.test"]


def test_cors_origins_from_dotenv_file(tmp_path) -> None:
    """Regression: pydantic-settings JSON-decodes list fields from .env sources.

    Without ``NoDecode`` the comma-separated form used in .env.example blows up
    with ``SettingsError: error parsing value for field "cors_origins"`` before
    the validator ever runs.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CORS_ORIGINS=http://localhost:3000,http://localhost:8080\n", encoding="utf-8"
    )

    configured = Settings(_env_file=env_file)
    assert configured.cors_origins == ["http://localhost:3000", "http://localhost:8080"]


def test_cors_origins_json_form_from_dotenv_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('CORS_ORIGINS=["http://d.test"]\n', encoding="utf-8")

    configured = Settings(_env_file=env_file)
    assert configured.cors_origins == ["http://d.test"]


def test_broker_and_backend_fall_back_to_redis_url() -> None:
    configured = Settings(redis_url="redis://cache:6379/9")
    assert configured.broker_url == "redis://cache:6379/9"
    assert configured.result_backend == "redis://cache:6379/9"


def test_explicit_celery_urls_win() -> None:
    configured = Settings(
        redis_url="redis://cache:6379/0",
        celery_broker_url="redis://broker:6379/1",
        celery_result_backend="redis://backend:6379/2",
    )
    assert configured.broker_url == "redis://broker:6379/1"
    assert configured.result_backend == "redis://backend:6379/2"


def test_providers_default_to_mock_placeholders() -> None:
    """Phase 1 wires up no real AI provider (PRD section 35 item 18)."""
    configured = Settings()
    assert configured.llm_provider == "mock"
    assert configured.image_provider == "mock"
    assert configured.video_provider == "mock"
    assert configured.tts_provider == "mock"


@pytest.mark.parametrize(
    "aws_like", ["sqlite+pysqlite:///:memory:", "postgresql+psycopg://u:p@h/d"]
)
def test_database_flavour_detection(aws_like: str) -> None:
    assert Settings(database_url=aws_like).is_sqlite is aws_like.startswith("sqlite")
