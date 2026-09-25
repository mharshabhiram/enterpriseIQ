"""
Admin service (project brief sections 14-15, 29).

Unlike dashboard_service, every query here is org-wide with no visibility
or ownership filtering - that's the whole point of an admin view. Access
control is enforced entirely at the route layer (require_role(UserRole.ADMIN)
on every route in app.api.routes.admin), not repeated here.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.document import Document
from app.repositories import audit_log_repository, conversation_repository, document_repository, user_repository
from app.utils import audit_actions

_RECENT_UPLOADS_LIMIT = 5
_RECENT_ACTIVITY_LIMIT = 10
_TOP_QUERIES_LIMIT = 10
_QUERY_RESOURCE_PREFIX = "query:"


@dataclass
class AdminStatsData:
    total_documents: int
    documents_by_status: dict
    total_users: int
    users_by_role: dict
    total_conversations: int
    recent_uploads: List[Document]
    most_searched_queries: List[Tuple[str, int]]
    recent_activity: List[AuditLog]


async def get_stats(session: AsyncSession) -> AdminStatsData:
    total_documents = await document_repository.count_all(session)
    documents_by_status = await document_repository.count_all_by_status(session)
    total_users = await user_repository.count_all(session)
    users_by_role = await user_repository.count_all_by_role(session)
    total_conversations = await conversation_repository.count_all(session)
    recent_uploads = await document_repository.list_recent(session, limit=_RECENT_UPLOADS_LIMIT)

    raw_top_queries = await audit_log_repository.top_search_queries(
        session, audit_actions.SEARCH_PERFORMED, limit=_TOP_QUERIES_LIMIT
    )
    most_searched_queries = [
        (resource[len(_QUERY_RESOURCE_PREFIX) :] if resource.startswith(_QUERY_RESOURCE_PREFIX) else resource, count)
        for resource, count in raw_top_queries
    ]

    recent_activity = await audit_log_repository.list_all(session, limit=_RECENT_ACTIVITY_LIMIT)

    return AdminStatsData(
        total_documents=total_documents,
        documents_by_status=documents_by_status,
        total_users=total_users,
        users_by_role=users_by_role,
        total_conversations=total_conversations,
        recent_uploads=recent_uploads,
        most_searched_queries=most_searched_queries,
        recent_activity=recent_activity,
    )


async def list_audit_logs(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    user_id: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
) -> List[AuditLog]:
    return await audit_log_repository.list_all(
        session,
        skip=skip,
        limit=limit,
        user_id=user_id,
        action=action,
        created_after=created_after,
        created_before=created_before,
    )
