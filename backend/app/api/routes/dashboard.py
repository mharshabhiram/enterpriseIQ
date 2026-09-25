"""
Dashboard route (project brief section 14).

A new file, not in the original section 18 route list - dashboard
aggregation is a distinct concern from any single resource (users,
documents, chat) and open to every authenticated role, unlike admin.py's
routes, so it doesn't belong nested under either. Sections 18/37 both
explicitly allow improving the suggested structure when justified.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.dashboard import DashboardResponse
from app.services import dashboard_service

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(get_current_user),
) -> DashboardResponse:
    data = await dashboard_service.get_dashboard(session, actor)
    return DashboardResponse(
        documents_visible_total=data.documents_visible_total,
        documents_by_status=data.documents_by_status,
        my_uploaded_documents=data.my_uploaded_documents,
        my_conversations_total=data.my_conversations_total,
        recent_conversations=data.recent_conversations,
        recent_documents=data.recent_documents,
    )
