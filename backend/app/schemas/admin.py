"""Pydantic schemas for GET /api/admin/stats and GET /api/admin/audit-logs (project brief sections 14-15, 29)."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.document import DocumentResponse


class SearchQueryFrequency(BaseModel):
    query: str
    count: int


class AdminStatsResponse(BaseModel):
    """
    Org-wide statistics, unlike GET /api/dashboard's per-user-scoped view -
    ADMIN only (see require_role(UserRole.ADMIN) on the route). No
    visibility filtering: every document and every user counts here,
    regardless of who uploaded or can see what.
    """

    total_documents: int
    documents_by_status: Dict[str, int]
    total_users: int
    users_by_role: Dict[str, int]
    total_conversations: int
    recent_uploads: List[DocumentResponse]
    most_searched_queries: List[SearchQueryFrequency]
    recent_activity: List["AuditLogResponse"]


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: Optional[uuid.UUID]
    action: str
    resource: Optional[str]
    event_metadata: Optional[Dict[str, Any]]
    created_at: datetime


AdminStatsResponse.model_rebuild()
