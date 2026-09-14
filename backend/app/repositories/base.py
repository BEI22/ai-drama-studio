"""Generic repository primitives (PRD section 29: ``repositories/``).

Repositories are the only layer that touches the ORM session. They contain no
business rules -- those live in ``app/services/``.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy.orm import Session

from app.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Thin CRUD wrapper around a single ORM model.

    Deliberately small: subclasses add the query methods they need. Transactions
    are committed by the service layer (or the request scope), never implicitly
    by a read helper.
    """

    model: type[ModelT]

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, entity_id: Any) -> ModelT | None:
        return self.db.get(self.model, entity_id)

    def add(self, entity: ModelT) -> ModelT:
        self.db.add(entity)
        return entity

    def delete(self, entity: ModelT) -> None:
        self.db.delete(entity)

    def flush(self) -> None:
        self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, entity: ModelT) -> ModelT:
        self.db.refresh(entity)
        return entity

    def save(self, entity: ModelT) -> ModelT:
        """Add (if needed) + flush + commit + refresh."""
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity
