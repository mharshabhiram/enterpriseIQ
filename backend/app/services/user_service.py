import uuid

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.exceptions import Conflict, Forbidden, NotFound
from app.models import Document, User
from app.repositories.users import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.security.passwords import hash_password
from app.services.audit_service import AuditAction, record


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.users = UserRepository(db)

    def _role_id(self, name: str) -> int:
        role = self.users.role(name)
        if role is None:
            raise NotFound(f"Unknown role '{name}'.", code="ROLE_NOT_FOUND")
        return role.id

    def create(self, actor: User, data: UserCreate) -> User:
        if self.users.by_email(data.email):
            raise Conflict("An account with this email already exists.", code="EMAIL_TAKEN")
        user = self.users.add(
            User(
                name=data.name.strip(),
                email=data.email.lower(),
                password_hash=hash_password(data.password),
                role_id=self._role_id(data.role),
                department=data.department,
            )
        )
        record(self.db, AuditAction.USER_CREATED, actor.id, "user", user.id, {"role": data.role.upper()}, commit=False)
        self.db.commit()
        self.db.refresh(user)
        return user

    def update(self, actor: User, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = self.users.get(user_id)
        if user is None:
            raise NotFound("User not found.", code="USER_NOT_FOUND")
        if user.id == actor.id and (data.is_active is False or (data.role and data.role.upper() != user.role_name)):
            raise Forbidden("You can't disable yourself or change your own role.")
        if data.name is not None:
            user.name = data.name.strip()
        if data.department is not None:
            user.department = data.department
        if data.role and data.role.upper() != user.role_name:
            old = user.role_name
            user.role_id = self._role_id(data.role)
            user.token_version += 1  # force re-login with the new role
            record(self.db, AuditAction.ROLE_CHANGED, actor.id, "user", user.id, {"from": old, "to": data.role.upper()}, commit=False)
        if data.is_active is not None and data.is_active != user.is_active:
            user.is_active = data.is_active
            user.token_version += 1
        record(self.db, AuditAction.USER_UPDATED, actor.id, "user", user.id, data.model_dump(exclude_none=True), commit=False)
        self.db.commit()
        self.db.expire(user, ["role"])
        self.db.refresh(user)
        return user

    def delete(self, actor: User, user_id: uuid.UUID) -> None:
        user = self.users.get(user_id)
        if user is None:
            raise NotFound("User not found.", code="USER_NOT_FOUND")
        if user.id == actor.id:
            raise Forbidden("You can't delete your own account.")
        # Users who uploaded documents are disabled instead, to keep document ownership intact.
        if self.db.scalar(select(exists().where(Document.uploaded_by == user.id))):
            raise Conflict("This user owns documents. Disable the account instead.", code="USER_HAS_DOCUMENTS")
        self.db.delete(user)
        record(self.db, AuditAction.USER_DELETED, actor.id, "user", user_id, commit=False)
        self.db.commit()
