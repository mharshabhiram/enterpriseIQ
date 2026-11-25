from sqlalchemy.orm import Session

from app.exceptions import Conflict, Forbidden, InvalidCredentials
from app.models import RoleName, User
from app.repositories.users import UserRepository
from app.schemas.auth import RegisterRequest, TokenResponse
from app.security.jwt import create_access_token
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.services.audit_service import AuditAction, record

# Dummy hash so unknown emails take as long as wrong passwords (no user enumeration by timing).
_DUMMY_HASH = hash_password("dummy-password-for-timing")


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    def register(self, data: RegisterRequest) -> User:
        if self.users.by_email(data.email):
            raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN")
        role = self.users.role(RoleName.EMPLOYEE.value)
        if role is None:
            raise RuntimeError("Roles are not seeded; run `alembic upgrade head`.")
        user = self.users.add(
            User(name=data.name.strip(), email=data.email.lower(), password_hash=hash_password(data.password), role_id=role.id)
        )
        record(self.db, AuditAction.USER_REGISTERED, user.id, "user", user.id, commit=False)
        self.db.commit()
        self.db.refresh(user)
        return user

    def login(self, email: str, password: str) -> TokenResponse:
        user = self.users.by_email(email)
        if user is None:
            verify_password(password, _DUMMY_HASH)
            raise InvalidCredentials("Wrong email or password.")
        if not verify_password(password, user.password_hash):
            raise InvalidCredentials("Wrong email or password.")
        if not user.is_active:
            raise Forbidden("This account is disabled. Contact an administrator.", code="ACCOUNT_DISABLED")
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        token, expires = create_access_token(user.id, user.role_name, user.token_version)
        record(self.db, AuditAction.USER_LOGIN, user.id, "auth")
        return TokenResponse(access_token=token, expires_in=expires)

    def logout(self, user: User) -> None:
        """Revoke every token issued so far for this user."""
        user.token_version += 1
        record(self.db, AuditAction.USER_LOGOUT, user.id, "auth")
