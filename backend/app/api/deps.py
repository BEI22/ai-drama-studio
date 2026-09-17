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
from app.services.agent_service import AgentService
from app.services.auth_service import AuthService
from app.services.bible_service import CharacterService, LocationService
from app.services.episode_service import EpisodeService
from app.services.image_service import ImageService
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


def get_agent_service(db: DbSession) -> AgentService:
    return AgentService(db)


def get_character_service(db: DbSession) -> CharacterService:
    return CharacterService(db)


def get_location_service(db: DbSession) -> LocationService:
    return LocationService(db)


def get_episode_service(db: DbSession) -> EpisodeService:
    return EpisodeService(db)


def get_image_service(db: DbSession) -> ImageService:
    """Image generation service (PRD section 16: provider resolved inside)."""
    return ImageService(db)


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
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
CharacterServiceDep = Annotated[CharacterService, Depends(get_character_service)]
LocationServiceDep = Annotated[LocationService, Depends(get_location_service)]
EpisodeServiceDep = Annotated[EpisodeService, Depends(get_episode_service)]
ImageServiceDep = Annotated[ImageService, Depends(get_image_service)]

__all__ = [
    "AgentServiceDep",
    "AppSettings",
    "AuthServiceDep",
    "CharacterServiceDep",
    "CurrentUser",
    "DbSession",
    "EpisodeServiceDep",
    "ImageServiceDep",
    "LocationServiceDep",
    "ProjectServiceDep",
    "bearer_scheme",
    "get_agent_service",
    "get_auth_service",
    "get_character_service",
    "get_current_user",
    "get_db",
    "get_episode_service",
    "get_image_service",
    "get_location_service",
    "get_project_service",
    "get_settings",
]
