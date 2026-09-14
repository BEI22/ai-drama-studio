"""Authentication routes (PRD sections 27, 31 Phase 2).

POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status

from app.api.deps import AuthServiceDep, CurrentUser
from app.core.responses import ok
from app.schemas.auth import TokenResponse, UserLogin, UserOut, UserRegister

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_payload(auth: AuthServiceDep, user) -> dict:
    return TokenResponse(
        access_token=auth.issue_token(user),
        expires_in=auth.expires_in_seconds(),
        user=UserOut.model_validate(user),
    ).model_dump(mode="json")


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="注册并直接返回访问令牌",
)
def register(payload: UserRegister, auth: AuthServiceDep) -> dict:
    user = auth.register(payload)
    logger.info("user registered", extra={"user_id": str(user.id)})
    return ok(_token_payload(auth, user))


@router.post("/login", summary="登录并获取访问令牌")
def login(payload: UserLogin, auth: AuthServiceDep) -> dict:
    user = auth.authenticate(payload.email, payload.password)
    logger.info("user logged in", extra={"user_id": str(user.id)})
    return ok(_token_payload(auth, user))


@router.get("/me", summary="当前登录用户")
def me(user: CurrentUser) -> dict:
    return ok(UserOut.model_validate(user).model_dump(mode="json"))
