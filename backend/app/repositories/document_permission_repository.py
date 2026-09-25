"""Document permission repository - CRUD for DocumentPermission rows."""
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_permission import DocumentPermission
from app.models.enums import GranteeType, UserRole


async def create(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    grantee_type: GranteeType,
    role: Optional[UserRole] = None,
    user_id: Optional[uuid.UUID] = None,
) -> DocumentPermission:
    permission = DocumentPermission(
        document_id=document_id, grantee_type=grantee_type, role=role, user_id=user_id
    )
    session.add(permission)
    await session.flush()
    await session.refresh(permission)
    return permission


async def get_by_id(session: AsyncSession, permission_id: uuid.UUID) -> Optional[DocumentPermission]:
    return await session.get(DocumentPermission, permission_id)


async def list_for_document(session: AsyncSession, document_id: uuid.UUID) -> List[DocumentPermission]:
    result = await session.execute(
        select(DocumentPermission).where(DocumentPermission.document_id == document_id)
    )
    return list(result.scalars().all())


async def delete(session: AsyncSession, permission: DocumentPermission) -> None:
    await session.delete(permission)
    await session.flush()
