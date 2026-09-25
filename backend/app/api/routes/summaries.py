"""
Summarization and comparison routes (project brief sections 12-13).

Both nested under /api/documents per the API design in section 21
(POST /api/documents/{id}/summarize, POST /api/documents/compare). Open to
any authenticated role that can already *view* the document(s) involved -
RBAC is enforced by document_service.get_document (reused by both
services), the same visibility rule as everywhere else: summarizing or
comparing a document you can't view returns 404, not 403, so a restricted
document's existence still isn't leaked.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.repositories import audit_log_repository
from app.schemas.comparison import CompareRequest, CompareResponse, ComparisonCategory, DocumentRef
from app.schemas.summary import SummarizeRequest, SummarizeResponse
from app.services import comparison_service, summarization_service
from app.utils import audit_actions

router = APIRouter(prefix="/api/documents", tags=["summaries"])


@router.post("/{document_id}/summarize", response_model=SummarizeResponse)
async def summarize_document(
    document_id: uuid.UUID,
    payload: SummarizeRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> SummarizeResponse:
    result = await summarization_service.summarize_document(
        session, actor, document_id, payload.summary_type
    )

    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.DOCUMENT_SUMMARIZED,
        resource=f"document:{document_id}",
        metadata={"summary_type": payload.summary_type.value, "map_reduce_used": result.map_reduce_used},
    )

    return SummarizeResponse(
        document_id=result.document.id,
        document_name=result.document.original_filename,
        summary_type=result.summary_type,
        summary=result.summary,
        chunk_count=result.chunk_count,
        map_reduce_used=result.map_reduce_used,
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_documents(
    payload: CompareRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> CompareResponse:
    result = await comparison_service.compare_documents(
        session, actor, payload.document_id_a, payload.document_id_b
    )

    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.DOCUMENT_COMPARED,
        resource=f"documents:{payload.document_id_a},{payload.document_id_b}",
        metadata={"used_summaries": result.used_summaries},
    )

    return CompareResponse(
        document_a=DocumentRef(id=result.document_a.id, name=result.document_a.original_filename),
        document_b=DocumentRef(id=result.document_b.id, name=result.document_b.original_filename),
        overview=result.overview,
        categories=[ComparisonCategory(**c) for c in result.categories],
        additions=result.additions,
        removals=result.removals,
        used_summaries=result.used_summaries,
    )
