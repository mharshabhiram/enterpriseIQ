"""
Audit log repository.

A thin insert helper used by services to record security-relevant events
(project brief section 29). Kept as a repository function rather than a full
service since it has no business logic of its own - just "write this row."
"""
import uuid
from typing import Any, Optional

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
