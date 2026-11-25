import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Message


class ConversationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_owned(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None:
        return self.db.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id))

    def list_owned(self, user_id: uuid.UUID, limit: int = 100) -> list[Conversation]:
        return list(
            self.db.scalars(
                select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc()).limit(limit)
            )
        )

    def recent_messages(self, conversation_id: uuid.UUID, limit: int = 6) -> list[Message]:
        rows = self.db.scalars(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.desc()).limit(limit)
        )
        return list(reversed(list(rows)))
