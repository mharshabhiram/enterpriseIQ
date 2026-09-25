"""Pydantic schemas for POST /api/chat and /api/conversations."""
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import MessageRole


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Continue an existing conversation. Omit to start a new one.",
    )
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    similarity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @field_validator("question")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question cannot be empty or only whitespace.")
        return stripped


class ChatSource(BaseModel):
    """
    Citation shape per project brief section 9, enriched with `excerpt` and
    `section_title` (the brief's example is illustrative, not exhaustive) -
    a citation naming only a document and page number without showing the
    actual excerpt used isn't very useful to a person deciding whether to
    trust the answer. Used for the immediate POST /api/chat response, where
    the source data is always fresh and complete (see MessageSourceResponse
    for the historical/conversation-history equivalent, whose fields must be
    optional since the underlying document/chunk may since have been
    deleted).
    """

    document_id: uuid.UUID
    document_name: str
    chunk_id: uuid.UUID
    page: Optional[int]
    section_title: Optional[str]
    excerpt: str
    relevance_score: float


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    sources: List[ChatSource]


class MessageSourceResponse(BaseModel):
    """
    Historical citation, as stored on a MessageSource row. All
    document/chunk fields are optional: MessageSource.chunk_id is
    ON DELETE SET NULL, so a citation whose source document was later
    deleted degrades to "we don't know which document this was, but here's
    the relevance score at the time" rather than disappearing.
    """

    chunk_id: Optional[uuid.UUID]
    document_id: Optional[uuid.UUID]
    document_name: Optional[str]
    page: Optional[int]
    section_title: Optional[str]
    excerpt: Optional[str]
    relevance_score: float


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    sources: List[MessageSourceResponse]


class ConversationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: Optional[str]
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(ConversationSummaryResponse):
    messages: List[MessageResponse]
