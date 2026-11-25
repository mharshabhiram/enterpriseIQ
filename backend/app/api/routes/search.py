from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.ai.base import EmbeddingProvider
from app.api.dependencies import embedding_provider, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas.search import SearchRequest, SearchResponse, SearchResult
from app.security.rate_limit import limiter
from app.services.audit_service import AuditAction, record
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
@limiter.limit("60/minute")
def search(
    request: Request,
    data: SearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    embedder: EmbeddingProvider = Depends(embedding_provider),
) -> SearchResponse:
    chunks = RetrievalService(db, embedder).retrieve(user, data.query, top_k=data.top_k or get_settings().top_k * 2, filters=data.filters)
    results = [
        SearchResult(
            chunk_id=c.chunk_id, document_id=c.document_id, document_name=c.document_name, file_type=c.file_type,
            department=c.department, uploaded_by=c.uploaded_by, uploader_name=c.uploader_name,
            upload_timestamp=c.upload_timestamp, tags=c.tags, page=c.page, section=c.section, excerpt=c.text,
            similarity=c.similarity,
        )
        for c in chunks
    ]
    record(db, AuditAction.SEARCH_PERFORMED, user.id, "search", None, {"query": data.query[:200], "results": len(results)})
    return SearchResponse(query=data.query, results=results)
