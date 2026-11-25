import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider, LLMProvider
from app.api.dependencies import embedding_provider, get_current_user, llm_provider
from app.database import get_db
from app.exceptions import NotFound
from app.models import Conversation, Message, User
from app.repositories.conversations import ConversationRepository
from app.schemas.chat import ChatRequest, ChatResponse, ConversationDetail, ConversationOut, MessageOut, SourceOut
from app.security.rate_limit import limiter
from app.services.rag_service import RAGService

router = APIRouter(prefix="/api", tags=["chat"])


def _response(conversation: Conversation, message: Message) -> ChatResponse:
    return ChatResponse(
        conversation_id=conversation.id,
        answer=message.content,
        sources=[SourceOut.model_validate(s) for s in message.sources],
        message=MessageOut.model_validate(message),
    )


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
def chat(
    request: Request,
    data: ChatRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(llm_provider),
    embedder: EmbeddingProvider = Depends(embedding_provider),
) -> ChatResponse:
    conversation, message = RAGService(db, llm, embedder).ask(user, data.message, data.conversation_id)
    return _response(conversation, message)


@router.post("/conversations/{conversation_id}/regenerate", response_model=ChatResponse)
@limiter.limit("30/minute")
def regenerate(
    request: Request,
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(llm_provider),
    embedder: EmbeddingProvider = Depends(embedding_provider),
) -> ChatResponse:
    conversation, message = RAGService(db, llm, embedder).regenerate(user, conversation_id)
    return _response(conversation, message)


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Conversation]:
    return ConversationRepository(db).list_owned(user.id)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Conversation:
    conversation = ConversationRepository(db).get_owned(user.id, conversation_id)
    if conversation is None:
        raise NotFound("Conversation not found.", code="CONVERSATION_NOT_FOUND")
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    conversation = ConversationRepository(db).get_owned(user.id, conversation_id)
    if conversation is None:
        raise NotFound("Conversation not found.", code="CONVERSATION_NOT_FOUND")
    db.delete(conversation)
    db.commit()
