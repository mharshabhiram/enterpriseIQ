"""
User model.

Password hashing (Argon2/bcrypt via passlib) happens in
app.security.password - this model only stores the resulting hash, never a
plaintext password.
"""
import uuid
from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, Enum as SAEnum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import UserRole
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.conversation import Conversation
    from app.models.document import Document
    from app.models.document_permission import DocumentPermission


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, default=UserRole.EMPLOYEE
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Documents this user uploaded. If the user is deleted, uploaded_by is set
    # NULL on their documents rather than deleting the documents themselves
    # (see Document.uploaded_by) - so no `back_populates` cascade is defined
    # here for deletes.
    documents: Mapped[List["Document"]] = relationship(
        back_populates="uploader", foreign_keys="Document.uploaded_by"
    )
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    document_permissions: Mapped[List["DocumentPermission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="user")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
