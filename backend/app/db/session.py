"""
Async SQLAlchemy engine and session factory.

Models (Phase 2) will import `Base` from app.db.base. Repositories and the
`get_db` dependency (app.api.dependencies) use `async_session_factory` from
this module to obtain a session per request.
"""
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
