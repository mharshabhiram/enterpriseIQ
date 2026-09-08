"""
Shared SQLAlchemy declarative base.

All ORM models (Phase 2) inherit from `Base` so Alembic autogenerate can
discover them via `Base.metadata`.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
