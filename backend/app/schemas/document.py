"""Pydantic schemas for document resources."""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import DocumentVisibility, GranteeType, ProcessingStatus, UserRole


class DocumentResponse(BaseModel):
    """
    Public document metadata. Deliberately omits the internal on-disk
    `filename` (see Document.filename vs original_filename) - that's a
    storage detail, not something a client needs or should see.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    file_type: str
    file_size: int
    uploaded_by: Optional[uuid.UUID]
    processing_status: ProcessingStatus
    processing_error: Optional[str]
    page_count: Optional[int]
    chunk_count: int
    visibility: DocumentVisibility
    created_at: datetime
    updated_at: datetime


class DocumentPermissionCreate(BaseModel):
    """
    Body for POST /api/documents/{id}/permissions. Mirrors the database
    CHECK constraint on DocumentPermission: a ROLE grant needs `role` and no
    `user_id`; a USER grant needs `user_id` and no `role`. Validated here too
    so a malformed request gets a clear 422 instead of a raw DB constraint
    error.
    """

    grantee_type: GranteeType
    role: Optional[UserRole] = None
    user_id: Optional[uuid.UUID] = None

    @model_validator(mode="after")
    def _validate_grant_shape(self) -> "DocumentPermissionCreate":
        if self.grantee_type == GranteeType.ROLE:
            if self.role is None or self.user_id is not None:
                raise ValueError("A ROLE grant requires `role` to be set and `user_id` to be omitted.")
        else:  # GranteeType.USER
            if self.user_id is None or self.role is not None:
                raise ValueError("A USER grant requires `user_id` to be set and `role` to be omitted.")
        return self


class DocumentPermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    grantee_type: GranteeType
    role: Optional[UserRole]
    user_id: Optional[uuid.UUID]
    created_at: datetime


class DocumentUpdate(BaseModel):
    """Body for PATCH /api/documents/{id}. Only visibility can be changed post-upload."""

    visibility: Optional[DocumentVisibility] = Field(default=None)
