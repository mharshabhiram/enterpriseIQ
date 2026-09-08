"""
User repository.

All direct SQLAlchemy queries against the `users` table live here. Services
call these functions instead of building queries themselves, so the query
logic (and any future optimization, e.g. eager loading) has one home.
"""
import uuid
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.user import User


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    return await session.get(User, user_id)


async def get_by_email(session: AsyncSession, email: str) -> Optional[User]:
    result = await session.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession, skip: int = 0, limit: int = 50) -> List[User]:
    result = await session.execute(select(User).order_by(User.created_at).offset(skip).limit(limit))
    return list(result.scalars().all())


async def count_by_role(session: AsyncSession, role: UserRole) -> int:
    """Used to guard against ever deleting/demoting the last remaining admin."""
    from sqlalchemy import func

    result = await session.execute(
        select(func.count()).select_from(User).where(User.role == role, User.is_active.is_(True))
    )
    return result.scalar_one()


async def create(
    session: AsyncSession, *, name: str, email: str, password_hash: str, role: UserRole
) -> User:
    user = User(name=name, email=email.lower(), password_hash=password_hash, role=role)
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def delete(session: AsyncSession, user: User) -> None:
    await session.delete(user)
    await session.flush()
