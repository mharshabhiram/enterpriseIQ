"""Authorization rules.

`accessible_documents_clause` is the single source of truth for "who may read
which document". It is a SQL expression, so it is applied *inside* every query
— including the pgvector similarity search — and unauthorised chunks never
leave the database.
"""
from sqlalchemy import ColumnElement, and_, exists, false, or_, select, true

from app.models import Document, DocumentPermission, DocumentVisibility, RoleName, User


def accessible_documents_clause(user: User) -> ColumnElement[bool]:
    if not user.is_active:
        return false()
    if user.has_role(RoleName.ADMIN):
        return true()
    granted = exists(
        select(DocumentPermission.id).where(
            DocumentPermission.document_id == Document.id,
            or_(DocumentPermission.user_id == user.id, DocumentPermission.role_id == user.role_id),
        )
    )
    return or_(
        Document.visibility == DocumentVisibility.PUBLIC,
        Document.uploaded_by == user.id,
        and_(Document.visibility == DocumentVisibility.RESTRICTED, granted),
    )


def can_upload(user: User) -> bool:
    return user.is_active and user.has_role(RoleName.ADMIN, RoleName.MANAGER)


def can_manage_document(user: User, document: Document) -> bool:
    """Delete / re-process / change permissions."""
    if not user.is_active:
        return False
    if user.has_role(RoleName.ADMIN):
        return True
    return user.has_role(RoleName.MANAGER) and document.uploaded_by == user.id


def can_access_document(user: User, document: Document) -> bool:
    """Python mirror of `accessible_documents_clause` for already-loaded rows."""
    if not user.is_active:
        return False
    if user.has_role(RoleName.ADMIN) or document.uploaded_by == user.id:
        return True
    if document.visibility == DocumentVisibility.PUBLIC:
        return True
    return any(p.user_id == user.id or p.role_id == user.role_id for p in document.permissions)
