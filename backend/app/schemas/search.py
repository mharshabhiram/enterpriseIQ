import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SearchFilters(BaseModel):
    file_types: list[str] | None = None
    department: str | None = None
    uploaded_by: uuid.UUID | None = None
    tags: list[str] | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    document_ids: list[uuid.UUID] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    top_k: int | None = Field(default=None, ge=1, le=50)


class SearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    file_type: str
    department: str | None
    uploaded_by: uuid.UUID
    uploader_name: str | None
    upload_timestamp: datetime
    tags: list[str]
    page: int | None
    section: str | None
    excerpt: str
    similarity: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
