"""
MessageSource model.

Links an assistant Message to the DocumentChunk(s) it cited, with the
similarity score at the time of retrieval - this is what powers the
citations feature (project brief section 9).

`chunk_id` is nullable with ON DELETE SET NULL: if the source document is
later deleted, we keep the chat history and the relevance score but drop the
now-dangling link, rather than silently deleting part of the conversation.
"""
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document_chunk import DocumentChunk
    from app.models.message import Message


class MessageSource(Base):
    __tablename__ = "message_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)

    message: Mapped["Message"] = relationship(back_populates="sources")
    chunk: Mapped[Optional["DocumentChunk"]] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MessageSource message_id={self.message_id} chunk_id={self.chunk_id} score={self.relevance_score:.3f}>"
