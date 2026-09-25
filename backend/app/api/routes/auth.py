"""
Auth routes: registration, login, and the current-user endpoint.

Thin by design - all business logic lives in app.services.auth_service.
register/login carry stricter rate limits than the app-wide default (see
app.security.rate_limit): these are the two routes brute-force credential
stuffing and spam-registration attempts actually target.
"""
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.config import settings
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserResponse
from app.security.jwt import create_access_token
from app.security.rate_limit import limiter
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request, payload: RegisterRequest, session: AsyncSession = Depends(get_db)
) -> User:
    """Public self-registration. Always creates an EMPLOYEE account."""
    return await auth_service.register_user(
        session, name=payload.name, email=payload.email, password=payload.password
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(
    request: Request, payload: LoginRequest, session: AsyncSession = Depends(get_db)
) -> TokenResponse:
    user = await auth_service.authenticate_user(session, email=payload.email, password=payload.password)
    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
