"""Pydantic schemas for user resources."""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole


class UserResponse(BaseModel):
    """Public-facing user representation - never includes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: EmailStr
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreateByAdmin(BaseModel):
    """
    Used by POST /api/users (admin-only). Unlike self-registration, an admin
    may set the role directly - this is how Manager/Admin accounts get
    created after the initial seed.
    """

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = UserRole.EMPLOYEE


class UserUpdate(BaseModel):
    """Used by PATCH /api/users/{id} (admin-only). All fields optional (partial update)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
