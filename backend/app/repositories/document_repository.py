"""
Document repository.

`list_visible_to_user` / `is_visible_to_user` are the enforcement point for
project brief section 16: a RESTRICTED document is only visible if the
requester is an ADMIN, the uploader, or has an explicit DocumentPermission
grant (by role or by user id). This filtering happens in the SQL WHERE
clause itself, not as a post-query filter in Python - the same principle
the RAG retrieval query will follow in Phase 5.
"""
import uuid
from typing import List, Optional

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_permission import DocumentPermission
from app.models.enums import DocumentVisibility, GranteeType, ProcessingStatus, UserRole
from app.models.user import User


def visibility_clause(user: User):
    """SQLAlchemy boolean expression: does `user` have permission to see a given Document row?"""
    if user.role == UserRole.ADMIN:
        return True  # no filtering at all - admins see everything

    role_grant = exists().where(
        DocumentPermission.document_id == Document.id,
        DocumentPermission.grantee_type == GranteeType.ROLE,
        DocumentPermission.role == user.role,
    )
    user_grant = exists().where(
        DocumentPermission.document_id == Document.id,
        DocumentPermission.grantee_type == GranteeType.USER,
        DocumentPermission.user_id == user.id,
    )
    return or_(
        Document.visibility == DocumentVisibility.PUBLIC,
        Document.uploaded_by == user.id,
        role_grant,
        user_grant,
    )


async def create(
    session: AsyncSession,
    *,
    filename: str,
    original_filename: str,
    file_type: str,
    file_size: int,
    uploaded_by: uuid.UUID,
    visibility: DocumentVisibility,
) -> Document:
    document = Document(
        filename=filename,
        original_filename=original_filename,
        file_type=file_type,
        file_size=file_size,
        uploaded_by=uploaded_by,
        visibility=visibility,
        processing_status=ProcessingStatus.UPLOADED,
    )
    session.add(document)
    await session.flush()
    await session.refresh(document)
    return document


async def get_by_id(session: AsyncSession, document_id: uuid.UUID) -> Optional[Document]:
    return await session.get(Document, document_id)


async def get_visible_to_user(
    session: AsyncSession, user: User, document_id: uuid.UUID
) -> Optional[Document]:
    stmt = select(Document).where(Document.id == document_id, visibility_clause(user))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_visible_to_user(
    session: AsyncSession,
    user: User,
    *,
    skip: int = 0,
    limit: int = 50,
    file_type: Optional[str] = None,
    processing_status: Optional[ProcessingStatus] = None,
) -> List[Document]:
    stmt = select(Document).where(visibility_clause(user))
    if file_type is not None:
        stmt = stmt.where(Document.file_type == file_type)
    if processing_status is not None:
        stmt = stmt.where(Document.processing_status == processing_status)
    stmt = stmt.order_by(Document.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_processing_result(
    session: AsyncSession,
    document: Document,
    *,
    status: ProcessingStatus,
    page_count: Optional[int] = None,
    chunk_count: Optional[int] = None,
    processing_error: Optional[str] = None,
) -> Document:
    document.processing_status = status
    if page_count is not None:
        document.page_count = page_count
    if chunk_count is not None:
        document.chunk_count = chunk_count
    document.processing_error = processing_error
    await session.flush()
    return document


async def delete(session: AsyncSession, document: Document) -> None:
    await session.delete(document)
    await session.flush()


# --- Aggregations for the dashboard (Phase 9) ---


async def count_visible_to_user(session: AsyncSession, user: User) -> int:
    result = await session.execute(select(func.count()).select_from(Document).where(visibility_clause(user)))
    return result.scalar_one()


async def count_by_status_for_user(session: AsyncSession, user: User) -> dict[str, int]:
    """Status breakdown among documents visible to this user (personal dashboard scope)."""
    stmt = (
        select(Document.processing_status, func.count())
        .where(visibility_clause(user))
        .group_by(Document.processing_status)
    )
    result = await session.execute(stmt)
    return {status.value: count for status, count in result.all()}


async def count_uploaded_by(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.execute(select(func.count()).select_from(Document).where(Document.uploaded_by == user_id))
    return result.scalar_one()


async def count_all(session: AsyncSession) -> int:
    """Org-wide total, no visibility filtering - admin-only use (see admin_service)."""
    result = await session.execute(select(func.count()).select_from(Document))
    return result.scalar_one()


async def count_all_by_status(session: AsyncSession) -> dict[str, int]:
    """Org-wide status breakdown, no visibility filtering - admin-only use."""
    stmt = select(Document.processing_status, func.count()).group_by(Document.processing_status)
    result = await session.execute(stmt)
    return {status.value: count for status, count in result.all()}


async def list_recent(session: AsyncSession, *, limit: int = 5) -> List[Document]:
    """Org-wide most recent uploads, no visibility filtering - admin-only use."""
    stmt = select(Document).order_by(Document.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
