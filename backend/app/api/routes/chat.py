"""
Chat and conversation routes (project brief sections 8 and 11).

Two routers in this one file, matching the backend structure from the
original design doc (no separate conversations.py): `router` for
POST /api/chat, `conversations_router` for /api/conversations. Both are
included in app.main.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.repositories import audit_log_repository
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    ConversationDetailResponse,
    ConversationSummaryResponse,
    MessageResponse,
    MessageSourceResponse,
)
from app.services import chat_service
from app.utils import audit_actions

router = APIRouter(prefix="/api/chat", tags=["chat"])
conversations_router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ChatResponse:
    turn = await chat_service.send_message(
        session,
        actor,
        payload.question,
        conversation_id=payload.conversation_id,
        top_k=payload.top_k,
        similarity_threshold=payload.similarity_threshold,
    )

    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.CHAT_REQUEST,
        resource=f"conversation:{turn.conversation.id}",
        metadata={"question": payload.question[:200], "source_count": len(turn.sources)},
    )

    sources = [
        ChatSource(
            document_id=source.document_id,
            document_name=source.document_name,
            chunk_id=source.chunk_id,
            page=source.page_number,
            section_title=source.section_title,
            excerpt=source.excerpt,
            relevance_score=source.relevance_score,
        )
        for source in turn.sources
    ]
    return ChatResponse(
        conversation_id=turn.conversation.id,
        message_id=turn.assistant_message.id,
        answer=turn.answer,
        sources=sources,
    )


def _map_message(message) -> MessageResponse:
    sources = []
    for source in message.sources:
        chunk = source.chunk
        document = chunk.document if chunk else None
        sources.append(
            MessageSourceResponse(
                chunk_id=chunk.id if chunk else None,
                document_id=document.id if document else None,
                document_name=document.original_filename if document else None,
                page=chunk.page_number if chunk else None,
                section_title=chunk.section_title if chunk else None,
                excerpt=chunk.chunk_text if chunk else None,
                relevance_score=source.relevance_score,
            )
        )
    return MessageResponse(
        id=message.id, role=message.role, content=message.content, created_at=message.created_at, sources=sources
    )


@conversations_router.get("", response_model=list[ConversationSummaryResponse])
async def list_conversations(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    return await chat_service.list_conversations(session, actor, skip=skip, limit=limit)


@conversations_router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> ConversationDetailResponse:
    conversation, messages = await chat_service.get_conversation_with_messages(session, actor, conversation_id)
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_map_message(m) for m in messages],
    )


@conversations_router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> None:
    await chat_service.delete_conversation(session, actor, conversation_id)
    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.CONVERSATION_DELETED,
        resource=f"conversation:{conversation_id}",
    )
