"""Pydantic schemas for POST /api/documents/compare."""
import uuid
from typing import List

from pydantic import BaseModel


class CompareRequest(BaseModel):
    document_id_a: uuid.UUID
    document_id_b: uuid.UUID


class DocumentRef(BaseModel):
    id: uuid.UUID
    name: str


class ComparisonCategory(BaseModel):
    category: str
    differences: List[str]


class CompareResponse(BaseModel):
    document_a: DocumentRef
    document_b: DocumentRef
    overview: str
    categories: List[ComparisonCategory]
    additions: List[str]
    removals: List[str]
    used_summaries: bool
