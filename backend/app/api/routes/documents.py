import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider, LLMProvider
from app.api.dependencies import embedding_provider, get_current_user, llm_provider, require_uploader
from app.config import get_settings
from app.database import get_db
from app.exceptions import AppError, FileTooLarge
from app.models import DocumentChunk, DocumentStatus, DocumentVisibility, User
from app.repositories.documents import DocumentRepository
from app.schemas.document import (
    ChunkOut,
    CompareRequest,
    CompareResponse,
    DocumentOut,
    PermissionOut,
    PermissionsUpdate,
    SummaryRequest,
    SummaryResponse,
)
from app.services.audit_service import AuditAction, record
from app.services.comparison_service import ComparisonService
from app.services.document_service import DocumentService
from app.services.ingestion_service import process_document
from app.services.summarization_service import SummarizationService
from app.utils.files import absolute_path

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _uuid_list(raw: str) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(u.strip()) for u in raw.split(",") if u.strip()]
    except ValueError as exc:
        raise AppError("user_ids must be comma-separated UUIDs.", code="VALIDATION_ERROR", status_code=422) from exc


@router.post("", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(None, max_length=255),
    department: str | None = Form(None, max_length=120),
    tags: str = Form("", max_length=500),
    description: str | None = Form(None, max_length=2000),
    visibility: DocumentVisibility = Form(DocumentVisibility.PUBLIC),
    roles: str = Form("", description="Comma-separated role names for RESTRICTED documents"),
    user_ids: str = Form("", description="Comma-separated user ids for RESTRICTED documents"),
    user: User = Depends(require_uploader),
    db: Session = Depends(get_db),
) -> DocumentOut:
    limit = get_settings().max_file_size
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise FileTooLarge(f"File is larger than {limit // (1024 * 1024)} MB.")
    service = DocumentService(db)
    doc = service.upload(
        user,
        filename=file.filename or "document",
        data=data,
        title=title,
        department=department,
        tags=tags.split(","),
        description=description,
        visibility=visibility,
        roles=[r for r in roles.split(",") if r.strip()],
        user_ids=_uuid_list(user_ids),
    )
    background.add_task(process_document, doc.id)  # processing does not block the response
    return service.to_out(doc, user)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    status_filter: DocumentStatus | None = Query(None, alias="status"),
    q: str | None = Query(None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    service = DocumentService(db)
    return [service.to_out(d, user) for d in DocumentRepository(db).list_accessible(user, status_filter, q)]


@router.post("/compare", response_model=CompareResponse)
def compare(
    data: CompareRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(llm_provider),
    embedder: EmbeddingProvider = Depends(embedding_provider),
) -> CompareResponse:
    return ComparisonService(db, llm, embedder).compare(user, data.document_a_id, data.document_b_id, data.focus)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentOut:
    service = DocumentService(db)
    doc = service.get_for_user(user, document_id)
    record(db, AuditAction.DOCUMENT_ACCESSED, user.id, "document", doc.id)
    return service.to_out(doc, user)


@router.get("/{document_id}/chunks", response_model=list[ChunkOut])
def get_chunks(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DocumentChunk]:
    doc = DocumentService(db).get_for_user(user, document_id)
    return DocumentRepository(db).chunks(doc.id)


@router.get("/{document_id}/download")
def download(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    doc = DocumentService(db).get_for_user(user, document_id)
    record(db, AuditAction.DOCUMENT_DOWNLOADED, user.id, "document", doc.id)
    return FileResponse(absolute_path(doc.storage_path), filename=doc.original_filename)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    DocumentService(db).delete(user, document_id)


@router.get("/{document_id}/permissions", response_model=list[PermissionOut])
def get_permissions(document_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[PermissionOut]:
    doc = DocumentService(db).get_manageable(user, document_id)
    return [PermissionOut(id=p.id, role=p.role.name if p.role else None, user_id=p.user_id) for p in doc.permissions]


@router.put("/{document_id}/permissions", response_model=DocumentOut)
def set_permissions(
    document_id: uuid.UUID, data: PermissionsUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DocumentOut:
    service = DocumentService(db)
    return service.to_out(service.update_permissions(user, document_id, data), user)


@router.post("/{document_id}/reprocess", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def reprocess(
    document_id: uuid.UUID, background: BackgroundTasks, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> DocumentOut:
    service = DocumentService(db)
    doc = service.mark_for_reprocessing(user, document_id)
    background.add_task(process_document, doc.id)
    return service.to_out(doc, user)


@router.post("/{document_id}/summarize", response_model=SummaryResponse)
def summarize(
    document_id: uuid.UUID,
    data: SummaryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    llm: LLMProvider = Depends(llm_provider),
) -> SummaryResponse:
    return SummarizationService(db, llm).summarize(user, document_id, data.type)
