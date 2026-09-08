"""
JWT access tokens.

Design decision: the token payload carries only `sub` (the user id) plus
standard `exp`/`iat` claims - deliberately *not* the user's role. RBAC checks
(app.api.dependencies.get_current_user / require_role) always re-load the
user from the database on every request instead of trusting a role embedded
in the token. This means a role change or account deactivation takes effect
on the user's very next request rather than only after their token expires,
which matters more here than saving one DB lookup per request (see project
brief section 22: "Never trust frontend authorization" - the same principle
applies to trusting a stale claim baked into a token).
"""
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import settings
from app.utils.errors import InvalidTokenError

_TOKEN_TYPE = "bearer"


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID:
    """Decode and validate a JWT, returning the user id it was issued for.

    Raises InvalidTokenError for anything wrong with the token: bad
    signature, malformed payload, expiry, or a `sub` that isn't a valid UUID.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidTokenError("Could not validate authentication token.") from exc

    subject = payload.get("sub")
    if subject is None:
        raise InvalidTokenError("Authentication token is missing its subject claim.")

    try:
        return uuid.UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("Authentication token subject is not a valid user id.") from exc
