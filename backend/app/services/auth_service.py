"""Authentication service (PRD sections 27, 31 Phase 2, 36).

Owns the register/login rules. Routes stay thin and just translate HTTP.
"""

from __future__ import annotations

import uuid

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import UserRegister


class AuthService:
    def __init__(self, db) -> None:
        self.db = db
        self.users = UserRepository(db)

    # ------------------------------------------------------------------ write
    def register(self, payload: UserRegister) -> User:
        email = payload.email.strip().lower()
        if self.users.email_taken(email):
            raise ConflictError("该邮箱已被注册")
        user = self.users.create(email=email, password_hash=hash_password(payload.password))
        self.db.commit()
        self.db.refresh(user)
        return user

    # ------------------------------------------------------------------- read
    def authenticate(self, email: str, password: str) -> User:
        user = self.users.get_by_email(email)
        # Same error for unknown email and wrong password: don't leak which
        # emails are registered (PRD section 27).
        if user is None or not verify_password(password, user.password_hash):
            raise UnauthorizedError("邮箱或密码不正确")
        return user

    def load_user(self, user_id: str | uuid.UUID) -> User:
        """Resolve a user from a JWT ``sub`` claim.

        The claim is always a string, but the primary key column is ``Uuid`` --
        SQLAlchemy will not coerce a string for us, so parse it explicitly. An
        unparseable subject means a tampered/invalid token, not a server error.
        """
        try:
            parsed = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise UnauthorizedError("Token 主体无效") from exc

        user = self.users.get(parsed)
        if user is None:
            raise UnauthorizedError("用户不存在或已注销")
        return user

    # ------------------------------------------------------------------ token
    @staticmethod
    def issue_token(user: User) -> str:
        return create_access_token(str(user.id), extra_claims={"email": user.email})

    @staticmethod
    def expires_in_seconds() -> int:
        return settings.access_token_expire_minutes * 60


def get_auth_service() -> AuthService:
    """Standalone factory for non-request contexts (scripts, workers, tests)."""
    return AuthService(SessionLocal())
