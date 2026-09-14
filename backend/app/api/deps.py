"""Shared FastAPI dependencies (PRD section 27).

``get_current_user`` is the single authentication gate: any route that takes
``CurrentUser`` is guaranteed to have a verified, existing user.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.project_service import ProjectService

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

# auto_error=False so we can raise our own enveloped UNAUTHORIZED error instead
# of Starlette's bare 403.
bearer_scheme = HTTPBearer(auto_error=False, description="Bearer <access_token>")


def get_auth_service(db: DbSession) -> AuthService:
    return AuthService(db)


def get_project_service(db: DbSession) -> ProjectService:
    return ProjectService(db)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("缺少访问令牌")

    claims = decode_access_token(credentials.credentials)
    subject = claims.get("sub")
    if not subject:
        raise UnauthorizedError("Token 缺少 subject")

    return auth.load_user(subject)


CurrentUser = Annotated[User, Depends(get_current_user)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]

__all__ = [
    "AppSettings",
    "AuthServiceDep",
    "CurrentUser",
    "DbSession",
    "ProjectServiceDep",
    "bearer_scheme",
    "get_auth_service",
    "get_current_user",
    "get_db",
    "get_project_service",
    "get_settings",
]
