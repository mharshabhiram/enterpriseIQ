"""FastAPI dependencies: current user, role guards, AI providers."""
import uuid
from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider, LLMProvider
from app.database import get_db
from app.exceptions import Forbidden, Unauthorized
from app.models import RoleName, User
from app.security.jwt import decode_access_token
from app.services.audit_service import AuditAction, record
from app.services.embedding_service import get_embedding_provider, get_llm_provider

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise Unauthorized("Sign in to continue.")
    payload = decode_access_token(credentials.credentials)
    try:
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise Unauthorized("Invalid authentication token.", code="INVALID_TOKEN") from exc
    if user is None or payload.get("tv") != user.token_version:
        raise Unauthorized("Your session is no longer valid. Please sign in again.", code="TOKEN_REVOKED")
    if not user.is_active:
        raise Forbidden("This account is disabled.", code="ACCOUNT_DISABLED")
    return user


def require_roles(*roles: RoleName) -> Callable[..., User]:
    def guard(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not user.has_role(*roles):
            record(db, AuditAction.PERMISSION_DENIED, user.id, "endpoint", None, {"required": [r.value for r in roles]})
            raise Forbidden("You don't have permission to do this.")
        return user

    return guard


require_admin = require_roles(RoleName.ADMIN)
require_uploader = require_roles(RoleName.ADMIN, RoleName.MANAGER)


def llm_provider() -> LLMProvider:
    return get_llm_provider()


def embedding_provider() -> EmbeddingProvider:
    return get_embedding_provider()
