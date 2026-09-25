"""Pydantic schemas for GET /api/dashboard (project brief section 14 - role-aware personal dashboard)."""
from typing import Dict, List

from pydantic import BaseModel

from app.schemas.chat import ConversationSummaryResponse
from app.schemas.document import DocumentResponse


class DashboardResponse(BaseModel):
    """
    Scoped to the requesting user via the same RBAC-filtered queries used
    everywhere else (document_repository.visibility_clause,
    conversation_repository's per-user filtering) - this is what makes the
    dashboard naturally "change based on role" (brief section 14) without
    needing separate role-specific response shapes: an EMPLOYEE's
    `documents_visible_total` reflects only what they can see, a MANAGER's
    `my_uploaded_documents` reflects their own uploads, and so on.
    """

    documents_visible_total: int
    documents_by_status: Dict[str, int]
    my_uploaded_documents: int
    my_conversations_total: int
    recent_conversations: List[ConversationSummaryResponse]
    recent_documents: List[DocumentResponse]
