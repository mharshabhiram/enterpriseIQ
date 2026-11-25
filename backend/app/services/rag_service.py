import re
import uuid

from sqlalchemy.orm import Session

from app.ai.base import ChatMessage, EmbeddingProvider, LLMProvider
from app.ai.prompts import NOT_FOUND_ANSWER, RAG_SYSTEM_PROMPT, format_context
from app.config import get_settings
from app.exceptions import NotFound
from app.models import Conversation, Message, MessageRole, MessageSource, User
from app.repositories.conversations import ConversationRepository
from app.services.audit_service import AuditAction, record
from app.services.retrieval_service import RetrievalService, select_context

_CITATION = re.compile(r"\[(S\d+(?:\s*,\s*S?\d+)*)\]")


def extract_citations(answer: str) -> list[int]:
    found: set[int] = set()
    for group in _CITATION.findall(answer):
        for part in group.split(","):
            digits = part.strip().lstrip("S")
            if digits.isdigit():
                found.add(int(digits))
    return sorted(found)


class RAGService:
    def __init__(self, db: Session, llm: LLMProvider, embedder: EmbeddingProvider) -> None:
        self.db = db
        self.llm = llm
        self.retrieval = RetrievalService(db, embedder)
        self.conversations = ConversationRepository(db)
        self.settings = get_settings()

    def ask(self, user: User, question: str, conversation_id: uuid.UUID | None = None) -> tuple[Conversation, Message]:
        question = question.strip()
        if conversation_id:
            conversation = self.conversations.get_owned(user.id, conversation_id)
            if conversation is None:
                raise NotFound("Conversation not found.", code="CONVERSATION_NOT_FOUND")
        else:
            conversation = Conversation(user_id=user.id, title=question[:70])
            self.db.add(conversation)
            self.db.flush()

        history = self.conversations.recent_messages(conversation.id, limit=6)
        self.db.add(Message(conversation_id=conversation.id, role=MessageRole.USER, content=question))
        self.db.flush()
        return conversation, self._answer(user, conversation, question, history)

    def regenerate(self, user: User, conversation_id: uuid.UUID) -> tuple[Conversation, Message]:
        conversation = self.conversations.get_owned(user.id, conversation_id)
        if conversation is None:
            raise NotFound("Conversation not found.", code="CONVERSATION_NOT_FOUND")
        messages = self.conversations.recent_messages(conversation.id, limit=20)
        if messages and messages[-1].role == MessageRole.ASSISTANT:
            self.db.delete(messages.pop())
            self.db.flush()
        last_user = next((m for m in reversed(messages) if m.role == MessageRole.USER), None)
        if last_user is None:
            raise NotFound("Nothing to regenerate.", code="NOTHING_TO_REGENERATE")
        history = [m for m in messages if m.id != last_user.id][-6:]
        return conversation, self._answer(user, conversation, last_user.content, history)

    def _answer(self, user: User, conversation: Conversation, question: str, history: list[Message]) -> Message:
        # Short follow-ups ("and for managers?") are retrieved together with the previous question.
        previous_user = next((m.content for m in reversed(history) if m.role == MessageRole.USER), None)
        retrieval_query = f"{previous_user}\n{question}" if previous_user and len(question) < 120 else question
        chunks = self.retrieval.retrieve(user, retrieval_query)  # permission-filtered in SQL
        context = select_context(chunks, self.settings.max_context_chars)

        sources = [
            {"source_number": i + 1, "document_name": c.document_name, "page": c.page, "section": c.section, "text": c.text}
            for i, c in enumerate(context)
        ]
        if not context:
            answer = NOT_FOUND_ANSWER  # don't even call the LLM: nothing it may use
        else:
            messages = [ChatMessage("system", RAG_SYSTEM_PROMPT)]
            messages += [ChatMessage(m.role.value, m.content[:3000]) for m in history]  # type: ignore[arg-type]
            messages.append(ChatMessage("user", f"Sources:\n\n{format_context(sources)}\n\n===\n\nQuestion: {question}"))
            answer = self.llm.generate(messages)

        not_found = answer.lower().startswith("i couldn't find this")
        cited = set() if not_found else set(extract_citations(answer))
        message = Message(conversation_id=conversation.id, role=MessageRole.ASSISTANT, content=answer)
        for i, chunk in enumerate(context, start=1):
            if i in cited:
                message.sources.append(
                    MessageSource(
                        source_number=i,
                        document_id=chunk.document_id,
                        chunk_id=chunk.chunk_id,
                        document_name=chunk.document_name,
                        page=chunk.page,
                        section=chunk.section,
                        excerpt=chunk.text,
                        relevance_score=chunk.similarity,
                    )
                )
        self.db.add(message)
        record(
            self.db,
            AuditAction.CHAT_REQUEST,
            user.id,
            "conversation",
            conversation.id,
            {"retrieved": len(chunks), "cited": len(message.sources)},
            commit=False,
        )
        self.db.commit()
        self.db.refresh(message)
        return message
