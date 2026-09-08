"""
Shared FastAPI dependencies: DB session, current-user resolution, and RBAC
role guards.

`get_current_user` always re-loads the user from the database (see
app.security.jwt for why the token itself carries no role claim) and
rejects deactivated accounts. `require_role` builds on top of it, so every
protected route composes from these same two primitives - there is no
separate code path anywhere else that re-implements "is this user allowed."
"""
from typing import AsyncGenerator, Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import user_repository
from app.security.jwt import decode_access_token
from app.utils.errors import InactiveUserError, InsufficientPermissionsError, InvalidTokenError

_bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    description="Paste the access token returned by POST /api/auth/login.",
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async DB session, committing on success."""
    async with async_session_factory() as session:
        yield session
        await session.commit()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    user_id = decode_access_token(credentials.credentials)
    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise InvalidTokenError("The user for this token no longer exists.")
    if not user.is_active:
        raise InactiveUserError("This account has been deactivated.")
    return user


def require_role(*allowed_roles: UserRole) -> Callable[[User], User]:
    """
    Dependency factory guarding a route to specific roles, e.g.:

        @router.delete("/{user_id}")
        async def delete_user(..., actor: User = Depends(require_role(UserRole.ADMIN))):
            ...
    """

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise InsufficientPermissionsError(
                "This action requires one of the following roles: "
                + ", ".join(role.value for role in allowed_roles)
                + "."
            )
        return current_user

    return _dependency
