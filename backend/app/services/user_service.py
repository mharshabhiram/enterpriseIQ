"""
User service.

Business logic behind the admin-only /api/users endpoints. Two independent
safety rules are enforced here (not just in routes), so they hold no matter
which future route or script calls into this service:

- An admin can never delete their own account through this API - that
  always has to be done by a *different* admin. A simple, absolute rule
  that avoids an admin's own session yanking their account out from
  under them mid-request.
- The last remaining active ADMIN can never be demoted away from ADMIN,
  deactivated, or deleted - by anyone, including themselves - otherwise
  the system would have no admin left to fix the situation. This check is
  purely numeric (how many active admins exist right now), so an admin
  *can* step down or deactivate their own account as long as at least one
  other active admin exists to take over.

  Note: combined with require_role(ADMIN) at the route layer (the actor
  is always an active admin) and the absolute self-delete rule above, the
  numeric guard can only ever actually fire via *self*-role-change or
  *self*-deactivation in practice - never via delete, and never via one
  admin acting on a different admin (there's always at least the actor
  left). It's kept as an explicit, independent check anyway so the
  invariant holds at the service layer regardless of which route (or
  future route) calls into it - see tests/test_auth.py for a test that
  exercises it directly, bypassing routes entirely.
"""
import uuid
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.user import User
from app.repositories import audit_log_repository, user_repository
from app.schemas.user import UserCreateByAdmin, UserUpdate
from app.security.password import hash_password
from app.utils import audit_actions
from app.utils.errors import EmailAlreadyExistsError, InvalidOperationError, UserNotFoundError


async def list_users(session: AsyncSession, *, skip: int = 0, limit: int = 50) -> List[User]:
    return await user_repository.list_all(session, skip=skip, limit=limit)


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise UserNotFoundError(f"User '{user_id}' does not exist.")
    return user


async def create_user(session: AsyncSession, *, actor: User, data: UserCreateByAdmin) -> User:
    existing = await user_repository.get_by_email(session, data.email)
    if existing is not None:
        raise EmailAlreadyExistsError(f"An account with email '{data.email}' already exists.")

    user = await user_repository.create(
        session,
        name=data.name,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.USER_CREATED_BY_ADMIN,
        resource=f"user:{user.id}",
        metadata={"role": user.role.value},
    )
    return user


async def _assert_not_last_active_admin(session: AsyncSession, target: User) -> None:
    """
    Guards any change that would remove `target` from the pool of active
    admins (role change away from ADMIN, deactivation, or deletion).
    Deliberately actor-agnostic - it only asks "how many active admins
    exist right now," so it applies the same whether an admin is acting on
    someone else or on themselves.
    """
    if target.role == UserRole.ADMIN and target.is_active:
        active_admins = await user_repository.count_by_role(session, UserRole.ADMIN)
        if active_admins <= 1:
            raise InvalidOperationError(
                "Cannot demote, deactivate, or delete the last remaining active admin."
            )


async def update_user(
    session: AsyncSession, *, actor: User, user_id: uuid.UUID, data: UserUpdate
) -> User:
    target = await get_user(session, user_id)

    if data.role is not None and data.role != target.role:
        if target.role == UserRole.ADMIN:
            await _assert_not_last_active_admin(session, target)
        old_role = target.role
        target.role = data.role
        await audit_log_repository.record_event(
            session,
            user_id=actor.id,
            action=audit_actions.ROLE_CHANGED,
            resource=f"user:{target.id}",
            metadata={"old_role": old_role.value, "new_role": data.role.value},
        )

    if data.is_active is not None and data.is_active != target.is_active:
        if not data.is_active:
            await _assert_not_last_active_admin(session, target)
        target.is_active = data.is_active
        await audit_log_repository.record_event(
            session,
            user_id=actor.id,
            action=audit_actions.USER_REACTIVATED if data.is_active else audit_actions.USER_DEACTIVATED,
            resource=f"user:{target.id}",
        )

    if data.name is not None and data.name != target.name:
        target.name = data.name
        await audit_log_repository.record_event(
            session, user_id=actor.id, action=audit_actions.USER_UPDATED, resource=f"user:{target.id}"
        )

    await session.flush()
    await session.refresh(target)
    return target


async def delete_user(session: AsyncSession, *, actor: User, user_id: uuid.UUID) -> None:
    target = await get_user(session, user_id)

    if target.id == actor.id:
        raise InvalidOperationError("Admins cannot delete their own account.")
    await _assert_not_last_active_admin(session, target)

    # Log before deleting: the FK is ON DELETE SET NULL, but the resource
    # string below still records which user/email was removed.
    await audit_log_repository.record_event(
        session,
        user_id=actor.id,
        action=audit_actions.USER_DELETED,
        resource=f"user:{target.id}",
        metadata={"email": target.email},
    )
    await user_repository.delete(session, target)

