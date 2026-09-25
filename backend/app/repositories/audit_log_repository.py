"""
Audit log repository.

`record_event` is a thin insert helper used by services to record
security-relevant events (project brief section 29). The read functions
below (added in Phase 9) back the admin panel's audit log view and search
statistics.
"""
import uuid
from datetime import datetime
from typing import Any, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record_event(
    session: AsyncSession,
    *,
    user_id: Optional[uuid.UUID],
    action: str,
    resource: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> AuditLog:
    entry = AuditLog(user_id=user_id, action=action, resource=resource, event_metadata=metadata)
    session.add(entry)
    await session.flush()
    return entry


async def list_all(
    session: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    user_id: Optional[uuid.UUID] = None,
    action: Optional[str] = None,
    created_after: Optional[datetime] = None,
    created_before: Optional[datetime] = None,
) -> List[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if created_after is not None:
        stmt = stmt.where(AuditLog.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(AuditLog.created_at <= created_before)
    stmt = stmt.offset(skip).limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def top_search_queries(session: AsyncSession, action: str, *, limit: int = 10) -> List[Tuple[str, int]]:
    """
    Frequency count of exact past search-query strings (the `resource`
    column on SEARCH_PERFORMED audit entries). This is genuinely just exact-
    string frequency, not semantic topic clustering - two differently-worded
    questions about the same policy are counted separately. Real "most
    searched *topics*" (brief section 14) would need clustering/embedding-
    based grouping, which is out of scope here and documented as a future
    improvement rather than silently approximated.
    """
    stmt = (
        select(AuditLog.resource, func.count().label("count"))
        .where(AuditLog.action == action, AuditLog.resource.is_not(None))
        .group_by(AuditLog.resource)
        .order_by(func.count().desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(resource, count) for resource, count in result.all()]
