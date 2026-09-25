"""
Dashboard service (project brief section 14).

Every query here is scoped to the requesting user via the same RBAC
primitives used throughout the app (document_repository.visibility_clause,
conversation_repository's per-user filtering) - there's no separate
role-branching logic in this service; the dashboard "changes based on
role" simply because an EMPLOYEE's visible-documents query and an ADMIN's
visible-documents query naturally return different rows.
"""
from dataclasses import dataclass
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.document import Document
from app.models.user import User
from app.repositories import conversation_repository, document_repository

_RECENT_LIMIT = 5


@dataclass
class DashboardData:
    documents_visible_total: int
    documents_by_status: dict
    my_uploaded_documents: int
    my_conversations_total: int
    recent_conversations: List[Conversation]
    recent_documents: List[Document]


async def get_dashboard(session: AsyncSession, user: User) -> DashboardData:
    documents_visible_total = await document_repository.count_visible_to_user(session, user)
    documents_by_status = await document_repository.count_by_status_for_user(session, user)
    my_uploaded_documents = await document_repository.count_uploaded_by(session, user.id)
    my_conversations_total = await conversation_repository.count_for_user(session, user.id)
    recent_conversations = await conversation_repository.list_for_user(session, user.id, limit=_RECENT_LIMIT)
    recent_documents = await document_repository.list_visible_to_user(session, user, limit=_RECENT_LIMIT)

    return DashboardData(
        documents_visible_total=documents_visible_total,
        documents_by_status=documents_by_status,
        my_uploaded_documents=my_uploaded_documents,
        my_conversations_total=my_conversations_total,
        recent_conversations=recent_conversations,
        recent_documents=recent_documents,
    )
