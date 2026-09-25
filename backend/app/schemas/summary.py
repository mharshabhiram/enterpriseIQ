"""Pydantic schemas for POST /api/documents/{id}/summarize."""
import uuid
from enum import Enum

from pydantic import BaseModel


class SummaryType(str, Enum):
    """
    Not a DB enum - summaries are generated on demand and never persisted
    (there's no Summary table), so this lives at the schema layer only.
    """

    SHORT = "SHORT"
    DETAILED = "DETAILED"
    EXECUTIVE = "EXECUTIVE"


class SummarizeRequest(BaseModel):
    summary_type: SummaryType = SummaryType.SHORT


class SummarizeResponse(BaseModel):
    document_id: uuid.UUID
    document_name: str
    summary_type: SummaryType
    summary: str
    chunk_count: int
    map_reduce_used: bool
