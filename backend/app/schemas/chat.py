import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SourceOut(ORMModel):
    source_number: int
    document_id: uuid.UUID | None
    document_name: str
    page: int | None
    section: str | None
    chunk_id: uuid.UUID | None
    excerpt: str
    relevance_score: float


class MessageOut(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    sources: list[SourceOut] = []


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=2, max_length=4000)


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    answer: str
    sources: list[SourceOut]
    message: MessageOut


class ConversationOut(ORMModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
