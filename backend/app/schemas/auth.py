"""Pydantic schemas for the /api/auth endpoints."""
from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserResponse


class RegisterRequest(BaseModel):
    """
    Public self-registration. Deliberately has no `role` field: every
    self-registered account is an EMPLOYEE (see auth_service.register_user).
    Promoting someone to MANAGER/ADMIN is an admin-only action via
    PATCH /api/users/{id} - self-registration can never grant elevated
    privileges, regardless of what a client sends.
    """

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: UserResponse
