"""
Search route (project brief section 10: Knowledge Search).

Open to any authenticated role - RBAC is enforced inside the retrieval
query itself (document_chunk_repository.search_similar), not by the route.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.repositories import audit_log_repository
from app.schemas.search import SearchRequest, SearchResponse
from app.services import retrieval_service
from app.utils import audit_actions

router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    payload: SearchRequest,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> SearchResponse:
    results = await retrieval_service.search(
        session,
        actor,
        payload.query,
        top_k=payload.top_k,
        similarity_threshold=payload.similarity_threshold,
        file_type=payload.file_type,
        uploaded_by=payload.uploaded_by,
        created_after=payload.created_after,
        created_before=payload.created_before,
    )
    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.SEARCH_PERFORMED,
        resource=f"query:{payload.query[:200]}",
        metadata={"result_count": len(results)},
    )
    return SearchResponse(query=payload.query, results=results)
