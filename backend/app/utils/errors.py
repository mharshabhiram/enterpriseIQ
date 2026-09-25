"""
Centralized application errors.

Every error that should reach the API as a structured, predictable JSON body
(see app.main's exception handlers) subclasses AppError. Routes/services
raise these instead of fastapi.HTTPException directly, so the response shape
is consistent everywhere:

    {"error": {"code": "INVALID_CREDENTIALS", "message": "..."}}
"""
from fastapi import status


class AppError(Exception):
    """Base class for all domain errors that map to a specific HTTP response."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APPLICATION_ERROR"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class InvalidCredentialsError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_CREDENTIALS"


class InvalidTokenError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_TOKEN"


class InactiveUserError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "INACTIVE_USER"


class InsufficientPermissionsError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "INSUFFICIENT_PERMISSIONS"


class EmailAlreadyExistsError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "EMAIL_ALREADY_EXISTS"


class UserNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "USER_NOT_FOUND"


class DocumentNotFoundError(AppError):
    """Defined now for the consistent-error-shape design; used starting Phase 4."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "DOCUMENT_NOT_FOUND"


class InvalidOperationError(AppError):
    """Generic 400 for well-formed-but-not-allowed requests (e.g. self-demotion)."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVALID_OPERATION"


class UnsupportedFileTypeError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "UNSUPPORTED_FILE_TYPE"


class FileTooLargeError(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "FILE_TOO_LARGE"


class FileValidationError(AppError):
    """The file's actual content doesn't match its claimed type, or is corrupt/unreadable."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "FILE_VALIDATION_ERROR"


class DocumentPermissionNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "DOCUMENT_PERMISSION_NOT_FOUND"


class EmbeddingProviderError(AppError):
    """The embedding provider (external API or misconfiguration) failed."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "EMBEDDING_PROVIDER_ERROR"


class LLMProviderError(AppError):
    """The LLM provider (external API or misconfiguration) failed."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "LLM_PROVIDER_ERROR"


class ConversationNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "CONVERSATION_NOT_FOUND"
