"""Shared pytest fixtures.

Environment variables are set *before* any ``app.*`` import so that settings and
the SQLAlchemy engine are built for the test run (in-memory SQLite, no external
services required).

.. important::
   The LLM settings are pinned here on purpose. ``Settings`` also reads the
   repository ``.env``, so a developer who points ``LLM_PROVIDER`` at a real
   vendor would otherwise make the suite call that vendor's API -- tests would
   become slow, flaky, non-deterministic and dependent on a paid key. Pinning
   keeps the suite hermetic and offline no matter what ``.env`` says.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# A file-backed SQLite database is used (not :memory:) because the TestClient
# exercises the app lifespan, which disposes the engine on shutdown -- an
# in-memory database would be destroyed mid-session.
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="ai_studio_tests_"))

os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{(_TEST_DB_DIR / 'test.db').as_posix()}"
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"

# --- hermetic AI providers ---------------------------------------------------
# Tests must never touch a real model. The mock provider is deterministic and
# offline; the base URL points at an unroutable address so that if a test ever
# does escape to the network it fails immediately instead of hanging.
os.environ["LLM_PROVIDER"] = "mock"
os.environ["IMAGE_PROVIDER"] = "mock"
os.environ["VIDEO_PROVIDER"] = "mock"
os.environ["TTS_PROVIDER"] = "mock"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
os.environ["MOCK_LLM_FAIL_TIMES"] = "0"
os.environ["MOCK_LLM_LATENCY_MS"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401  (registers tables on Base.metadata)
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

TEST_TABLES = ("characters", "locations", "episodes", "projects", "users")


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Create the schema once for the whole test session."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables(_schema: None) -> None:
    """Truncate every table after each test so tests stay independent.

    Children first: SQLite does not enforce FK order here, but Postgres would.
    """
    yield
    with engine.begin() as connection:
        for table in TEST_TABLES:
            connection.execute(Base.metadata.tables[table].delete())


@pytest.fixture(autouse=True)
def _reset_agent_state():
    """Keep the provider singleton and prompt cache from leaking between tests."""
    from app.providers.llm import reset_llm_provider
    from app.utils.prompts import clear_cache

    reset_llm_provider()
    clear_cache()
    yield
    reset_llm_provider()
    clear_cache()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
