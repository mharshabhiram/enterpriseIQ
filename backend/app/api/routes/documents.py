"""
Document routes.

Upload is ADMIN/MANAGER-only (project brief section 4 gives employees no
upload capability). Listing/viewing/downloading is open to any
authenticated role, with visibility itself enforced inside
document_service/document_repository - not by hiding the route. Deletion
and visibility changes require require_role(ADMIN, MANAGER) at the route
plus an ownership check inside the service (a MANAGER may only manage
documents they uploaded). Permission management is ADMIN-only.
"""
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db, require_role
from app.models.document import Document
from app.models.enums import DocumentVisibility, ProcessingStatus, UserRole
from app.models.user import User
from app.schemas.document import (
    DocumentPermissionCreate,
    DocumentPermissionResponse,
    DocumentResponse,
    DocumentUpdate,
)
from app.services import document_service
from app.services.ingestion_service import process_document

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    visibility: DocumentVisibility = DocumentVisibility.RESTRICTED,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
) -> Document:
    document = await document_service.upload_document(session, actor=actor, file=file, visibility=visibility)
    # Scheduled after the route returns; by the time it runs, get_db's
    # commit has already happened (see ingestion_service's module docstring),
    # so the freshly-created document row is visible to its own session.
    background_tasks.add_task(process_document, document.id)
    return document


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    file_type: str | None = Query(default=None),
    status_filter: ProcessingStatus | None = Query(default=None, alias="status"),
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> list[Document]:
    return await document_service.list_documents(
        session, actor, skip=skip, limit=limit, file_type=file_type, processing_status=status_filter
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> Document:
    return await document_service.get_document(session, actor, document_id)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    from fastapi.responses import FileResponse

    from app.ingestion.storage import build_storage_path

    document = await document_service.get_document_for_download(session, actor, document_id)
    return FileResponse(
        path=build_storage_path(document.filename),
        filename=document.original_filename,
        media_type="application/octet-stream",
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
) -> Document:
    if payload.visibility is not None:
        return await document_service.update_visibility(session, actor, document_id, payload.visibility)
    return await document_service.get_document(session, actor, document_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
) -> None:
    await document_service.delete_document(session, actor, document_id)


# --- Permissions (ADMIN-only) ---


@router.post(
    "/{document_id}/permissions",
    response_model=DocumentPermissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_permission(
    document_id: uuid.UUID,
    payload: DocumentPermissionCreate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN)),
):
    return await document_service.add_permission(session, actor, document_id, payload)


@router.get("/{document_id}/permissions", response_model=list[DocumentPermissionResponse])
async def list_permissions(
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN)),
):
    return await document_service.list_permissions(session, actor, document_id)


@router.delete("/{document_id}/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_permission(
    document_id: uuid.UUID,
    permission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN)),
) -> None:
    await document_service.revoke_permission(session, actor, document_id, permission_id)
