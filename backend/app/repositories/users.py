import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Role, User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.db.get(User, user_id)

    def by_email(self, email: str) -> User | None:
        return self.db.scalar(select(User).where(func.lower(User.email) == email.lower()))

    def list(self) -> list[User]:
        return list(self.db.scalars(select(User).order_by(User.created_at.desc())))

    def count(self) -> int:
        return self.db.scalar(select(func.count(User.id))) or 0

    def role(self, name: str) -> Role | None:
        return self.db.scalar(select(Role).where(Role.name == name.upper()))

    def add(self, user: User) -> User:
        self.db.add(user)
        self.db.flush()
        return user
