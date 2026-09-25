"""
Admin routes (project brief sections 14-15, 29): org-wide statistics and
audit log access. Every route here is ADMIN-only.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.admin import AdminStatsResponse, AuditLogResponse, SearchQueryFrequency
from app.services import admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role(UserRole.ADMIN)),
) -> AdminStatsResponse:
    data = await admin_service.get_stats(session)
    return AdminStatsResponse(
        total_documents=data.total_documents,
        documents_by_status=data.documents_by_status,
        total_users=data.total_users,
        users_by_role=data.users_by_role,
        total_conversations=data.total_conversations,
        recent_uploads=data.recent_uploads,
        most_searched_queries=[
            SearchQueryFrequency(query=query, count=count) for query, count in data.most_searched_queries
        ],
        recent_activity=data.recent_activity,
    )


@router.get("/audit-logs", response_model=list[AuditLogResponse])
async def list_audit_logs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: uuid.UUID | None = Query(default=None),
    action: str | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role(UserRole.ADMIN)),
):
    return await admin_service.list_audit_logs(
        session,
        skip=skip,
        limit=limit,
        user_id=user_id,
        action=action,
        created_after=created_after,
        created_before=created_before,
    )
