"""Application error taxonomy and error codes.

Every business failure is raised as an :class:`AppError` subclass carrying a
stable machine-readable ``code`` (see PRD section 23). The global handlers in
``app.main`` turn these into the unified response envelope.
"""

from __future__ import annotations

from typing import Any


class ErrorCode:
    """Stable error codes returned to clients."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    UNSUPPORTED = "UNSUPPORTED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    GENERATION_FAILED = "GENERATION_FAILED"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base class for all expected, client-facing errors."""

    code: str = ErrorCode.INTERNAL_ERROR
    status_code: int = 500
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class ValidationError(AppError):
    code = ErrorCode.VALIDATION_ERROR
    status_code = 422
    message = "Request validation failed"


class NotFoundError(AppError):
    code = ErrorCode.NOT_FOUND
    status_code = 404
    message = "Resource not found"


class ConflictError(AppError):
    code = ErrorCode.CONFLICT
    status_code = 409
    message = "Resource conflict"


class UnauthorizedError(AppError):
    code = ErrorCode.UNAUTHORIZED
    status_code = 401
    message = "Not authenticated"


class ForbiddenError(AppError):
    code = ErrorCode.FORBIDDEN
    status_code = 403
    message = "Not enough permissions"


class UnsupportedError(AppError):
    code = ErrorCode.UNSUPPORTED
    status_code = 400
    message = "Unsupported operation"


class ProviderError(AppError):
    code = ErrorCode.PROVIDER_ERROR
    status_code = 502
    message = "Upstream AI provider failed"


class GenerationFailedError(AppError):
    code = ErrorCode.GENERATION_FAILED
    status_code = 422
    message = "Generation failed"


class TimeoutError_(AppError):
    code = ErrorCode.TIMEOUT
    status_code = 504
    message = "Operation timed out"
