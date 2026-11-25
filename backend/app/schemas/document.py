import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import DocumentStatus, DocumentVisibility
from app.schemas.common import ORMModel


class PermissionOut(BaseModel):
    id: uuid.UUID
    role: str | None
    user_id: uuid.UUID | None


class DocumentOut(ORMModel):
    id: uuid.UUID
    title: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    uploaded_by: uuid.UUID
    uploader_name: str | None = None
    upload_timestamp: datetime = Field(validation_alias="created_at")
    department: str | None
    tags: list[str]
    description: str | None
    processing_status: DocumentStatus
    processing_error: str | None
    page_count: int | None
    chunk_count: int
    visibility: DocumentVisibility
    embedding_model: str | None
    can_manage: bool = False


class ChunkOut(ORMModel):
    id: uuid.UUID
    chunk_index: int
    chunk_text: str
    page_number: int | None
    section: str | None


class PermissionsUpdate(BaseModel):
    visibility: DocumentVisibility
    roles: list[str] = Field(default_factory=list, max_length=20)
    user_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class CompareRequest(BaseModel):
    document_a_id: uuid.UUID
    document_b_id: uuid.UUID
    focus: str | None = Field(default=None, max_length=300)


class SummaryRequest(BaseModel):
    type: str = Field(default="short", pattern="^(short|detailed|executive)$")


class SummaryResponse(BaseModel):
    document_id: uuid.UUID
    title: str
    type: str
    strategy: str
    sections_processed: int
    summary: str


class Change(BaseModel):
    type: str
    topic: str
    document_a: str = ""
    document_b: str = ""
    explanation: str = ""


class Category(BaseModel):
    name: str
    changes: list[Change]


class CompareResponse(BaseModel):
    document_a: str
    document_b: str
    overview: str
    key_differences: list[str]
    categories: list[Category]
