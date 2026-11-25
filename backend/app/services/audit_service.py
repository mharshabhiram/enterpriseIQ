import uuid
from enum import Enum

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import AuditLog

log = get_logger("audit")


class AuditAction(str, Enum):
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    USER_REGISTERED = "USER_REGISTERED"
    USER_CREATED = "USER_CREATED"
    USER_UPDATED = "USER_UPDATED"
    USER_DELETED = "USER_DELETED"
    ROLE_CHANGED = "ROLE_CHANGED"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_PROCESSED = "DOCUMENT_PROCESSED"
    DOCUMENT_FAILED = "DOCUMENT_FAILED"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"
    DOCUMENT_ACCESSED = "DOCUMENT_ACCESSED"
    DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    SEARCH_PERFORMED = "SEARCH_PERFORMED"
    CHAT_REQUEST = "CHAT_REQUEST"
    SUMMARY_GENERATED = "SUMMARY_GENERATED"
    COMPARISON_GENERATED = "COMPARISON_GENERATED"


def record(
    db: Session,
    action: AuditAction,
    user_id: uuid.UUID | None,
    resource_type: str | None = None,
    resource_id: str | uuid.UUID | None = None,
    metadata: dict | None = None,
    commit: bool = True,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action.value,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            metadata_=metadata or {},
        )
    )
    log.info("audit", action=action.value, user_id=str(user_id) if user_id else None, resource_type=resource_type)
    if commit:
        db.commit()
