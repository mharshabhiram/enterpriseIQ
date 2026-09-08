"""
DocumentPermission model.

Implements the flexible access model from the project brief (section 16):
a RESTRICTED document (see Document.visibility) is readable only if at least
one DocumentPermission row grants it - either to the requesting user's role
(grantee_type=ROLE) or to that specific user (grantee_type=USER). PUBLIC
documents need no rows here at all.

A CHECK constraint enforces that `role` is set for ROLE grants and `user_id`
is set for USER grants, so the two grant types can't be mixed up at the
database level.
"""
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import GranteeType, UserRole

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class DocumentPermission(Base):
    __tablename__ = "document_permissions"
    __table_args__ = (
        CheckConstraint(
            "(grantee_type = 'ROLE' AND role IS NOT NULL AND user_id IS NULL) OR "
            "(grantee_type = 'USER' AND user_id IS NOT NULL AND role IS NULL)",
            name="ck_document_permissions_grantee_consistency",
        ),
        Index("ix_document_permissions_document_role", "document_id", "role"),
        Index("ix_document_permissions_document_user", "document_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    grantee_type: Mapped[GranteeType] = mapped_column(
        SAEnum(GranteeType, name="grantee_type"), nullable=False
    )
    role: Mapped[Optional[UserRole]] = mapped_column(
        SAEnum(UserRole, name="user_role", create_type=False), nullable=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship(back_populates="permissions")
    user: Mapped[Optional["User"]] = relationship(back_populates="document_permissions")

    def __repr__(self) -> str:  # pragma: no cover
        target = f"role={self.role}" if self.grantee_type == GranteeType.ROLE else f"user_id={self.user_id}"
        return f"<DocumentPermission document_id={self.document_id} {target}>"
