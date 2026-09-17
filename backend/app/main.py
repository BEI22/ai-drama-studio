"""FastAPI application entrypoint (PRD section 31, Phase 1).

Run locally::

    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.context import get_request_id
from app.core.database import engine
from app.core.exceptions import AppError, ErrorCode
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.responses import fail
from app.core.signing import verify_storage_signature
from app.schemas.health import HealthResponse
from app.storage import StorageError, get_storage

configure_logging(settings.log_level, settings.log_json)
logger = logging.getLogger("app.main")

_HTTP_STATUS_TO_CODE = {
    400: ErrorCode.VALIDATION_ERROR,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: "METHOD_NOT_ALLOWED",
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    502: ErrorCode.PROVIDER_ERROR,
    504: ErrorCode.TIMEOUT,
}


def _probe_database() -> None:
    """Log database connectivity at startup without blocking app boot."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        logger.info("database connection ok")
    except Exception as exc:  # noqa: BLE001 - boot must not depend on the DB
        logger.warning("database unreachable at startup: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "starting %s v%s (env=%s)",
        settings.app_name,
        settings.app_version,
        settings.environment,
    )
    _probe_database()
    yield
    logger.info("shutting down %s", settings.app_name)
    engine.dispose()


def create_app() -> FastAPI:
    """Application factory -- used by uvicorn, tests and the Docker image."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI Studio -- AI comic-drama / series auto-production platform.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[settings.request_id_header],
    )

    _register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/health", response_model=HealthResponse, tags=["health"], summary="Liveness probe")
    def root_health() -> HealthResponse:
        """Bare liveness contract from PRD section 31: ``{"status": "ok"}``."""
        return HealthResponse(status="ok")

    @app.get("/", tags=["meta"], summary="Service metadata")
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
            "docs": "/docs",
            "health": "/health",
            "api": settings.api_v1_prefix,
        }

    _mount_static(app)
    return app


def _mount_static(app: FastAPI) -> None:
    """Serve stored files behind a signed, expiring URL (PRD section 27).

    This began as a plain public ``/static`` mount in Phase 1, when no file
    existed yet. That mount had to go once assets became real: a public path
    makes the URL the only capability, so any leaked or guessed path would read
    another user's generated images permanently, which section 27 forbids on two
    counts ("用户只能访问自己的 project", "文件 URL 使用签名 URL").

    The signature is checked before the filesystem is touched, so a bad signature
    can never probe for file existence.
    """

    @app.get("/files/{key:path}", include_in_schema=False)
    def serve_stored_file(
        key: str,
        expires: int | None = None,
        sig: str | None = None,
    ) -> Response:
        if not verify_storage_signature(key, expires, sig):
            raise HTTPException(status_code=403, detail="文件链接无效或已过期")
        try:
            data = get_storage().read(key)
        except StorageError:
            raise HTTPException(status_code=404, detail="文件不存在") from None
        media_type, _ = mimetypes.guess_type(key)
        return Response(
            content=data,
            media_type=media_type or "application/octet-stream",
            headers={"Cache-Control": "private, max-age=300"},
        )


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        logger.warning("app error: %s (%s)", exc.message, exc.code)
        return fail(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            details=exc.details,
            request_id=get_request_id(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [
            {
                "loc": list(error.get("loc", [])),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return fail(
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            status_code=422,
            details=details,
            request_id=get_request_id(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = _HTTP_STATUS_TO_CODE.get(exc.status_code, "HTTP_ERROR")
        return fail(
            code,
            str(exc.detail),
            status_code=exc.status_code,
            request_id=get_request_id(),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled exception: %s", exc)
        return fail(
            ErrorCode.INTERNAL_ERROR,
            "Internal server error",
            status_code=500,
            request_id=get_request_id(),
        )


app = create_app()
