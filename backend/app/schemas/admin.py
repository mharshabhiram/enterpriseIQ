import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class StatsOut(BaseModel):
    total_documents: int
    completed_documents: int
    processing_documents: int
    failed_documents: int
    total_users: int
    total_chunks: int
    total_conversations: int
    stale_embedding_documents: int
    top_searches: list[tuple[str, int]]
    recent_uploads: list[dict]
    recent_conversations: list[dict]
    activity_last_14_days: list[dict]


class AuditLogOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    resource_type: str | None
    resource_id: str | None
    metadata: dict = Field(validation_alias="metadata_")
    created_at: datetime
