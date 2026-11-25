import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_admin
from app.database import get_db
from app.models import User
from app.repositories.users import UserRepository
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services.user_service import UserService

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[User]:
    return UserRepository(db).list()


@router.get("/directory", response_model=list[UserOut])
def directory(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[User]:
    """Colleague list used when sharing a document."""
    return [u for u in UserRepository(db).list() if u.is_active]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
    return UserService(db).create(admin, data)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, data: UserUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> User:
    return UserService(db).update(admin, user_id, data)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> None:
    UserService(db).delete(admin, user_id)
