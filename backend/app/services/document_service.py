"""
Document service.

Route-level `require_role` handles "is this role allowed to hit this
endpoint at all" (e.g. only ADMIN/MANAGER can upload). This service handles
the data-dependent RBAC that role alone can't express:

- Viewing/downloading a document goes through
  document_repository.get_visible_to_user, which folds in visibility,
  ownership, and DocumentPermission grants at the SQL level (see that
  repository's docstring). A document that isn't visible to the requester
  and a document that doesn't exist produce the identical 404 - deliberately,
  so a RESTRICTED document's existence is never leaked to someone without
  access to it.
- Deleting or changing a document's visibility additionally requires being
  the ADMIN or the document's own uploader (a MANAGER can manage documents
  they uploaded, not anyone else's - see _can_manage).
- Granting/listing/revoking permissions is ADMIN-only, enforced entirely at
  the route layer (require_role(UserRole.ADMIN)) since there's no
  ownership nuance for it.
"""
import uuid
from typing import List, Optional

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ingestion import storage
from app.ingestion.validators import validate_content, validate_extension, validate_size
from app.models.document import Document
from app.models.document_permission import DocumentPermission
from app.models.enums import DocumentVisibility, GranteeType, ProcessingStatus, UserRole
from app.models.user import User
from app.repositories import audit_log_repository, document_permission_repository, document_repository, user_repository
from app.schemas.document import DocumentPermissionCreate
from app.utils import audit_actions
from app.utils.errors import (
    DocumentNotFoundError,
    DocumentPermissionNotFoundError,
    InsufficientPermissionsError,
    UserNotFoundError,
)


def _can_manage(actor: User, document: Document) -> bool:
    """Delete / change-visibility rights: ADMIN, or the MANAGER who uploaded it."""
    return actor.role == UserRole.ADMIN or document.uploaded_by == actor.id


async def upload_document(
    session: AsyncSession,
    *,
    actor: User,
    file: UploadFile,
    visibility: DocumentVisibility,
) -> Document:
    file_type = validate_extension(file.filename or "")
    stored_filename = storage.generate_stored_filename(file_type)

    file_size = await storage.save_upload(file, stored_filename, max_size=settings.max_file_size)
    try:
        validate_size(file_size)
        validate_content(storage.build_storage_path(stored_filename), file_type)
    except Exception:
        storage.delete_file(stored_filename)
        raise

    document = await document_repository.create(
        session,
        filename=stored_filename,
        original_filename=file.filename or stored_filename,
        file_type=file_type,
        file_size=file_size,
        uploaded_by=actor.id,
        visibility=visibility,
    )
    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.DOCUMENT_UPLOADED,
        resource=f"document:{document.id}",
        metadata={"file_type": file_type, "file_size": file_size},
    )
    return document


async def list_documents(
    session: AsyncSession,
    actor: User,
    *,
    skip: int = 0,
    limit: int = 50,
    file_type: Optional[str] = None,
    processing_status: Optional[ProcessingStatus] = None,
) -> List[Document]:
    return await document_repository.list_visible_to_user(
        session, actor, skip=skip, limit=limit, file_type=file_type, processing_status=processing_status
    )


async def get_document(session: AsyncSession, actor: User, document_id: uuid.UUID) -> Document:
    document = await document_repository.get_visible_to_user(session, actor, document_id)
    if document is None:
        raise DocumentNotFoundError(f"Document '{document_id}' does not exist.")
    return document


async def get_document_for_download(session: AsyncSession, actor: User, document_id: uuid.UUID) -> Document:
    document = await get_document(session, actor, document_id)
    await audit_log_repository.record_event(
        session, user_id=actor.id, action=audit_actions.DOCUMENT_DOWNLOADED, resource=f"document:{document.id}"
    )
    return document


async def update_visibility(
    session: AsyncSession, actor: User, document_id: uuid.UUID, visibility: DocumentVisibility
) -> Document:
    document = await get_document(session, actor, document_id)
    if not _can_manage(actor, document):
        raise InsufficientPermissionsError("Only an admin or this document's uploader can change its visibility.")

    if visibility != document.visibility:
        old_visibility = document.visibility
        document.visibility = visibility
        await session.flush()
        await audit_log_repository.record_event(
            session,
            user_id=actor.id,
            action=audit_actions.DOCUMENT_VISIBILITY_CHANGED,
            resource=f"document:{document.id}",
            metadata={"old": old_visibility.value, "new": visibility.value},
        )
    return document


async def delete_document(session: AsyncSession, actor: User, document_id: uuid.UUID) -> None:
    document = await get_document(session, actor, document_id)
    if not _can_manage(actor, document):
        raise InsufficientPermissionsError("Only an admin or this document's uploader can delete it.")

    stored_filename = document.filename
    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.DOCUMENT_DELETED,
        resource=f"document:{document.id}",
        metadata={"original_filename": document.original_filename},
    )
    await document_repository.delete(session, document)
    storage.delete_file(stored_filename)


# --- Permissions (ADMIN-only; enforced at the route layer) ---


async def add_permission(
    session: AsyncSession, actor: User, document_id: uuid.UUID, data: DocumentPermissionCreate
) -> DocumentPermission:
    document = await document_repository.get_by_id(session, document_id)
    if document is None:
        raise DocumentNotFoundError(f"Document '{document_id}' does not exist.")

    if data.grantee_type == GranteeType.USER:
        target_user = await user_repository.get_by_id(session, data.user_id)  # type: ignore[arg-type]
        if target_user is None:
            raise UserNotFoundError(f"User '{data.user_id}' does not exist.")

    permission = await document_permission_repository.create(
        session,
        document_id=document.id,
        grantee_type=data.grantee_type,
        role=data.role,
        user_id=data.user_id,
    )
    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.PERMISSION_GRANTED,
        resource=f"document:{document.id}",
        metadata={
            "grantee_type": data.grantee_type.value,
            "role": data.role.value if data.role else None,
            "user_id": str(data.user_id) if data.user_id else None,
        },
    )
    return permission


async def list_permissions(
    session: AsyncSession, actor: User, document_id: uuid.UUID
) -> List[DocumentPermission]:
    document = await document_repository.get_by_id(session, document_id)
    if document is None:
        raise DocumentNotFoundError(f"Document '{document_id}' does not exist.")
    return await document_permission_repository.list_for_document(session, document_id)


async def revoke_permission(
    session: AsyncSession, actor: User, document_id: uuid.UUID, permission_id: uuid.UUID
) -> None:
    permission = await document_permission_repository.get_by_id(session, permission_id)
    if permission is None or permission.document_id != document_id:
        raise DocumentPermissionNotFoundError(f"Permission '{permission_id}' does not exist on this document.")

    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.PERMISSION_REVOKED,
        resource=f"document:{document_id}",
        metadata={"permission_id": str(permission_id)},
    )
    await document_permission_repository.delete(session, permission)
