"""Message repository."""
import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document_chunk import DocumentChunk
from app.models.enums import MessageRole
from app.models.message import Message
from app.models.message_source import MessageSource
from app.schemas.search import SearchResultItem


async def create_message(
    session: AsyncSession, *, conversation_id: uuid.UUID, role: MessageRole, content: str
) -> Message:
    message = Message(conversation_id=conversation_id, role=role, content=content)
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return message


async def create_sources(
    session: AsyncSession, message_id: uuid.UUID, sources: List[SearchResultItem]
) -> List[MessageSource]:
    rows = [
        MessageSource(message_id=message_id, chunk_id=source.chunk_id, relevance_score=source.relevance_score)
        for source in sources
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def list_with_sources_for_conversation(
    session: AsyncSession, conversation_id: uuid.UUID
) -> List[Message]:
    """
    Loads every message in a conversation with sources - and each source's
    chunk and the chunk's document - eager-loaded in a bounded number of
    queries, so rendering conversation history doesn't N+1.
    """
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .options(
            selectinload(Message.sources).selectinload(MessageSource.chunk).selectinload(DocumentChunk.document)
        )
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())
