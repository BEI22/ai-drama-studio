"""Shared pytest fixtures.

Environment variables are set *before* any ``app.*`` import so that settings and
the SQLAlchemy engine are built for the test run (in-memory SQLite, no external
services required).
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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401  (registers tables on Base.metadata)
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

TEST_TABLES = ("episodes", "projects", "users")


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Create the schema once for the whole test session."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables(_schema: None) -> None:
    """Truncate every table after each test so tests stay independent."""
    yield
    with engine.begin() as connection:
        for table in TEST_TABLES:
            connection.execute(Base.metadata.tables[table].delete())


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
