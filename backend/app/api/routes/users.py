"""
User management routes - admin-only (see project brief section 4: user
management is exclusively an admin capability). Every route here is guarded
by `require_role(UserRole.ADMIN)`, enforced server-side regardless of what
the frontend shows or hides.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_role
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserCreateByAdmin, UserResponse, UserUpdate
from app.services import user_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role(UserRole.ADMIN)),
) -> list[User]:
    return await user_service.list_users(session, skip=skip, limit=limit)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreateByAdmin,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN)),
) -> User:
    return await user_service.create_user(session, actor=actor, data=payload)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role(UserRole.ADMIN)),
) -> User:
    return await user_service.get_user(session, user_id)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN)),
) -> User:
    return await user_service.update_user(session, actor=actor, user_id=user_id, data=payload)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role(UserRole.ADMIN)),
) -> None:
    await user_service.delete_user(session, actor=actor, user_id=user_id)
