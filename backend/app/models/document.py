"""
Document model.

Stores metadata about an uploaded file; the extracted/chunked content lives
in DocumentChunk rows, and the raw file itself lives on disk under
settings.upload_dir (see app.ingestion, Phase 4).
"""
import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import BigInteger, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import DocumentVisibility, ProcessingStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.document_chunk import DocumentChunk
    from app.models.document_permission import DocumentPermission
    from app.models.user import User


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Storage filename (e.g. a UUID-based name on disk) vs. the name the user
    # uploaded it as - kept separate so we never trust user input for paths.
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # SET NULL rather than CASCADE: deleting a user's account should not
    # silently delete every document they ever uploaded on behalf of the org.
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        SAEnum(ProcessingStatus, name="processing_status"),
        nullable=False,
        default=ProcessingStatus.UPLOADED,
        index=True,
    )
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    visibility: Mapped[DocumentVisibility] = mapped_column(
        SAEnum(DocumentVisibility, name="document_visibility"),
        nullable=False,
        default=DocumentVisibility.RESTRICTED,
    )

    uploader: Mapped[Optional["User"]] = relationship(
        back_populates="documents", foreign_keys=[uploaded_by]
    )
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index"
    )
    permissions: Mapped[List["DocumentPermission"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document id={self.id} filename={self.original_filename!r} status={self.processing_status}>"
