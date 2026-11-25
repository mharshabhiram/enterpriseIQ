from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_admin
from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, Conversation, Document, DocumentChunk, DocumentStatus, RoleName, User
from app.repositories.documents import DocumentRepository
from app.schemas.admin import AuditLogOut, StatsOut
from app.security.permissions import accessible_documents_clause
from app.services.ingestion_service import process_document

router = APIRouter(prefix="/api/admin", tags=["admin"])


def build_stats(db: Session, user: User) -> StatsOut:
    """Role-aware stats: admins see the whole system, others only what they can access."""
    is_admin = user.has_role(RoleName.ADMIN)
    counts = DocumentRepository(db).count_by_status(user)
    scope = select(Document).where(accessible_documents_clause(user))
    recent = db.scalars(scope.order_by(Document.created_at.desc()).limit(6)).unique().all()
    convo_q = select(Conversation).order_by(Conversation.updated_at.desc()).limit(5)
    if not is_admin:
        convo_q = convo_q.where(Conversation.user_id == user.id)

    # literal key (not a bind param) so SELECT and GROUP BY render the identical expression
    query_text = AuditLog.metadata_.op("->>")(literal_column("'query'"))
    searches = select(query_text, func.count()).where(AuditLog.action == "SEARCH_PERFORMED")
    if not is_admin:
        searches = searches.where(AuditLog.user_id == user.id)
    top = db.execute(searches.group_by(query_text).order_by(func.count().desc()).limit(6)).all()

    since = datetime.now(UTC) - timedelta(days=13)
    day = func.date_trunc("day", AuditLog.created_at)
    activity_q = select(day, AuditLog.action, func.count()).where(AuditLog.created_at >= since)
    if not is_admin:
        activity_q = activity_q.where(AuditLog.user_id == user.id)
    activity = [
        {"day": d.date().isoformat(), "action": a, "count": n}
        for d, a, n in db.execute(activity_q.group_by(day, AuditLog.action)).all()
    ]
    model = get_settings().ollama_embedding_model
    stale = db.scalar(
        select(func.count(Document.id)).where(
            Document.processing_status == DocumentStatus.COMPLETED, Document.embedding_model != model, accessible_documents_clause(user)
        )
    )
    return StatsOut(
        total_documents=sum(counts.values()),
        completed_documents=counts.get("COMPLETED", 0),
        processing_documents=counts.get("PROCESSING", 0) + counts.get("UPLOADED", 0),
        failed_documents=counts.get("FAILED", 0),
        total_users=db.scalar(select(func.count(User.id))) or 0,
        total_chunks=(db.scalar(select(func.count(DocumentChunk.id))) or 0) if is_admin else 0,
        total_conversations=db.scalar(select(func.count(Conversation.id)).where(Conversation.user_id == user.id)) or 0,
        stale_embedding_documents=stale or 0,
        top_searches=[(q or "", n) for q, n in top],
        recent_uploads=[
            {"id": str(d.id), "title": d.title, "status": d.processing_status.value, "file_type": d.file_type, "created_at": d.created_at.isoformat()}
            for d in recent
        ],
        recent_conversations=[{"id": str(c.id), "title": c.title, "updated_at": c.updated_at.isoformat()} for c in db.scalars(convo_q).all()],
        activity_last_14_days=activity,
    )


@router.get("/stats", response_model=StatsOut)
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> StatsOut:
    return build_stats(db, user)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    action: str | None = Query(None, max_length=50),
    limit: int = Query(200, ge=1, le=1000),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    return list(db.scalars(q))


@router.post("/reembed", status_code=202)
def reembed_stale(background: BackgroundTasks, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Re-process every document embedded with a different model than the configured one."""
    model = get_settings().ollama_embedding_model
    ids = list(db.scalars(select(Document.id).where(Document.embedding_model.is_not(None), Document.embedding_model != model)))
    for doc_id in ids:
        background.add_task(process_document, doc_id)
    return {"queued": len(ids)}
