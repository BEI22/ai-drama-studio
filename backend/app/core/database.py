"""SQLAlchemy engine, session factory and declarative base (PRD sections 14, 17)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, create_engine, func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# Deterministic constraint names -- required for sane Alembic autogenerate diffs.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class TimestampMixin:
    """``created_at`` / ``updated_at`` columns required by the PRD tables."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def build_engine(url: str | None = None) -> Engine:
    """Create an :class:`Engine`, applying SQLite-specific test settings."""
    database_url = url or settings.database_url
    kwargs: dict[str, Any] = {"echo": settings.database_echo, "future": True}

    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            # One shared in-memory DB across threads/connections (tests).
            kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = settings.database_pool_size
        kwargs["max_overflow"] = settings.database_max_overflow

    return create_engine(database_url, **kwargs)


engine: Engine = build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for scripts, workers and tests."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
