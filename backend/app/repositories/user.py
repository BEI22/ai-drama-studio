"""User data access."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        """Case-insensitive lookup -- emails are normalised on write."""
        statement = select(User).where(func.lower(User.email) == email.strip().lower())
        return self.db.execute(statement).scalar_one_or_none()

    def email_taken(self, email: str) -> bool:
        return self.get_by_email(email) is not None

    def create(self, *, email: str, password_hash: str) -> User:
        user = User(email=email.strip().lower(), password_hash=password_hash)
        self.db.add(user)
        self.db.flush()
        return user

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)
