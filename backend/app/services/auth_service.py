"""
Auth service.

Business logic for registration and login. Routes call these functions and
translate their return values/exceptions into HTTP responses - no query
building or password/JWT handling happens in the route layer.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.user import User
from app.repositories import audit_log_repository, user_repository
from app.security.password import hash_password, verify_password
from app.utils import audit_actions
from app.utils.errors import EmailAlreadyExistsError, InactiveUserError, InvalidCredentialsError


async def register_user(session: AsyncSession, *, name: str, email: str, password: str) -> User:
    """
    Public self-registration. Always creates an EMPLOYEE - there is no code
    path from this function to any other role, by design (see
    app.schemas.auth.RegisterRequest).
    """
    existing = await user_repository.get_by_email(session, email)
    if existing is not None:
        raise EmailAlreadyExistsError(f"An account with email '{email}' already exists.")

    user = await user_repository.create(
        session,
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.EMPLOYEE,
    )
    await audit_log_repository.record_event(
        session, user_id=user.id, action=audit_actions.USER_REGISTERED, resource=f"user:{user.id}"
    )
    return user


async def authenticate_user(session: AsyncSession, *, email: str, password: str) -> User:
    """
    Verify credentials and return the user on success.

    Deliberately raises the same InvalidCredentialsError whether the email
    doesn't exist or the password is wrong, so the API never reveals which
    emails are registered.
    """
    user = await user_repository.get_by_email(session, email)
    if user is None or not verify_password(password, user.password_hash):
        await audit_log_repository.record_event(
            session,
            user_id=user.id if user else None,
            action=audit_actions.USER_LOGIN_FAILED,
            resource=f"email:{email}",
        )
        raise InvalidCredentialsError("Incorrect email or password.")

    if not user.is_active:
        raise InactiveUserError("This account has been deactivated.")

    await audit_log_repository.record_event(
        session, user_id=user.id, action=audit_actions.USER_LOGIN, resource=f"user:{user.id}"
    )
    return user
