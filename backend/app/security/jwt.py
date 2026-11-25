"""JWT access tokens. `tv` (token version) lets the server revoke all tokens for a user."""
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import get_settings
from app.exceptions import Unauthorized


def create_access_token(user_id: uuid.UUID, role: str, token_version: int) -> tuple[str, int]:
    settings = get_settings()
    expires = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "tv": token_version,
        "iat": now,
        "exp": now + timedelta(seconds=expires),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm), expires


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp"]})
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your session has expired. Please sign in again.", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Invalid authentication token.", code="INVALID_TOKEN") from exc
