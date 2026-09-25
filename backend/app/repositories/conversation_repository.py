"""
Conversation repository.

Every read here is scoped to a specific user_id - conversations are private
to the person who had them, with no admin-visibility exception (unlike
documents). See app.services.chat_service for the rationale.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation


async def create(session: AsyncSession, user_id: uuid.UUID) -> Conversation:
    conversation = Conversation(user_id=user_id)
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation)
    return conversation


async def get_for_user(
    session: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Optional[Conversation]:
    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, skip: int = 0, limit: int = 50
) -> List[Conversation]:
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


async def touch(session: AsyncSession, conversation: Conversation) -> None:
    """
    Bump updated_at explicitly. The TimestampMixin's onupdate hook only
    fires when one of the Conversation row's *own* columns changes in the
    same flush - adding a child Message row doesn't trigger it - so
    "most recently active" ordering needs this explicit touch after each
    turn.
    """
    conversation.updated_at = datetime.now(timezone.utc)
    await session.flush()


async def delete(session: AsyncSession, conversation: Conversation) -> None:
    await session.delete(conversation)
    await session.flush()


async def count_for_user(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
    )
    return result.scalar_one()


async def count_all(session: AsyncSession) -> int:
    """Org-wide total, no per-user filtering - admin-only use (see admin_service)."""
    result = await session.execute(select(func.count()).select_from(Conversation))
    return result.scalar_one()
