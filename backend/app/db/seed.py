"""
Seed script: creates one ADMIN, one MANAGER, and one EMPLOYEE account for
local development, if they don't already exist.

Run with:
    python -m app.db.seed

Credentials are intentionally simple defaults for local development only
(see README "Seed Data" section) and must be changed before any shared or
production use - this script is not something you run against a real
deployment as-is.
"""
import asyncio

from app.db.session import async_session_factory
from app.models.enums import UserRole
from app.repositories import user_repository
from app.security.password import hash_password

SEED_USERS = [
    {
        "name": "Admin User",
        "email": "admin@enterpriseiq.local",
        "password": "Admin123!",
        "role": UserRole.ADMIN,
    },
    {
        "name": "Manager User",
        "email": "manager@enterpriseiq.local",
        "password": "Manager123!",
        "role": UserRole.MANAGER,
    },
    {
        "name": "Employee User",
        "email": "employee@enterpriseiq.local",
        "password": "Employee123!",
        "role": UserRole.EMPLOYEE,
    },
]


async def seed() -> None:
    async with async_session_factory() as session:
        for spec in SEED_USERS:
            existing = await user_repository.get_by_email(session, spec["email"])
            if existing is not None:
                print(f"skip (already exists): {spec['email']}")
                continue
            user = await user_repository.create(
                session,
                name=spec["name"],
                email=spec["email"],
                password_hash=hash_password(spec["password"]),
                role=spec["role"],
            )
            print(f"created: {user.email} ({user.role.value})")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
