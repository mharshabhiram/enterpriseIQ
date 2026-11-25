"""Centralised error types and handlers.

Every API error has the shape {"error": {"code": "...", "message": "..."}}.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"

    def __init__(self, message: str, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class InvalidCredentials(AppError):
    status_code, code = status.HTTP_401_UNAUTHORIZED, "INVALID_CREDENTIALS"


class Unauthorized(AppError):
    status_code, code = status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED"


class Forbidden(AppError):
    status_code, code = status.HTTP_403_FORBIDDEN, "FORBIDDEN"


class NotFound(AppError):
    status_code, code = status.HTTP_404_NOT_FOUND, "NOT_FOUND"


class Conflict(AppError):
    status_code, code = status.HTTP_409_CONFLICT, "CONFLICT"


class UnsupportedFile(AppError):
    status_code, code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_FILE"


class FileTooLarge(AppError):
    status_code, code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "FILE_TOO_LARGE"


class LLMUnavailable(AppError):
    status_code, code = status.HTTP_503_SERVICE_UNAVAILABLE, "LLM_UNAVAILABLE"


class EmbeddingUnavailable(AppError):
    status_code, code = status.HTTP_503_SERVICE_UNAVAILABLE, "EMBEDDING_UNAVAILABLE"


class ProcessingError(AppError):
    status_code, code = status.HTTP_422_UNPROCESSABLE_ENTITY, "DOCUMENT_PROCESSING_FAILED"


def error_body(code: str, message: str, details: object | None = None) -> dict:
    error: dict = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content=error_body("VALIDATION_ERROR", "Some fields are invalid.", details))

    @app.exception_handler(RateLimitExceeded)
    async def handle_rate_limit(_: Request, __: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content=error_body("RATE_LIMITED", "Too many requests. Please slow down."))

    @app.exception_handler(SQLAlchemyError)
    async def handle_db(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("database_error", exc_info=exc)
        return JSONResponse(status_code=500, content=error_body("DATABASE_ERROR", "A database error occurred."))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", exc_info=exc)
        return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "Something went wrong."))
