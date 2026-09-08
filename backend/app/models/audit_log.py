"""
AuditLog model.

Records sensitive/security-relevant events (project brief section 29):
logins, uploads, deletions, permission changes, etc. `user_id` is nullable
with ON DELETE SET NULL so the audit trail survives account deletion - losing
*who* did something is preferable to losing the record that it happened.

`event_metadata` (JSONB) holds action-specific details, e.g.
{"document_id": "...", "old_role": "EMPLOYEE", "new_role": "MANAGER"}.
"""
import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # e.g. USER_LOGIN, DOCUMENT_UPLOADED, DOCUMENT_DELETED, DOCUMENT_ACCESSED,
    # SEARCH_PERFORMED, CHAT_REQUEST, ROLE_CHANGED, PERMISSION_CHANGED.
    # Plain string (not a DB enum) so new event types don't require a migration.
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    event_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog id={self.id} action={self.action} user_id={self.user_id}>"
