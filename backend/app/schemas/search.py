"""Pydantic schemas for POST /api/search."""
import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    similarity_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    file_type: Optional[str] = None
    uploaded_by: Optional[uuid.UUID] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None


class SearchResultItem(BaseModel):
    document_id: uuid.UUID
    document_name: str
    chunk_id: uuid.UUID
    excerpt: str
    page_number: Optional[int]
    section_title: Optional[str]
    relevance_score: float


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResultItem]
