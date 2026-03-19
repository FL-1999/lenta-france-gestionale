from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import Role, RoleEnum, User, UserRole
from permissions import get_user_roles, has_perm
from auth import get_current_active_user, hash_password

router = APIRouter(
    prefix="/users",
    tags=["users"],
)


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None
    active_role: RoleEnum
    roles: list[RoleEnum]
    language: str | None = "it"
    can_switch_roles: bool = False


class UserOut(UserBase):
    id: int

    class Config:
        orm_mode = True


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    active_role: RoleEnum
    roles: list[RoleEnum]
    language: str | None = "it"
    can_switch_roles: bool = False


def _get_or_create_role(db: Session, role_name: RoleEnum) -> Role:
    role = db.query(Role).filter(Role.name == role_name).first()
    if role:
        return role
    role = Role(name=role_name, description=f"Ruolo {role_name.value}")
    db.add(role)
    db.flush()
    return role


def _user_to_schema(user: User) -> UserOut:
    roles = list(get_user_roles(user))
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        active_role=user.role,
        roles=roles,
        language=user.language,
        can_switch_roles=bool(getattr(user, "can_switch_roles", False)),
    )


@router.get("/", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not has_perm(current_user, "users.manage"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per vedere la lista utenti.",
        )

    users = (
        db.query(User)
        .options(joinedload(User.user_roles).joinedload(UserRole.role))
        .order_by(User.id)
        .all()
    )
    return [_user_to_schema(user) for user in users]


@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if not has_perm(current_user, "users.create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Non hai i permessi per creare nuovi utenti.",
        )

    existing = db.query(User).filter(User.email == user_in.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esiste già un utente con questa email.",
        )

    if len(user_in.password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La password deve avere almeno 4 caratteri.",
        )

    if not user_in.roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="È necessario assegnare almeno un ruolo.",
        )
    if user_in.active_role not in user_in.roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Il ruolo attivo deve essere tra i ruoli assegnati.",
        )

    can_switch_roles = bool(
        user_in.can_switch_roles
        and len(set(user_in.roles)) > 1
        and RoleEnum.admin in user_in.roles
    )

    db_user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        role=user_in.active_role,
        language=user_in.language or "it",
        can_switch_roles=can_switch_roles,
        hashed_password=hash_password(user_in.password),
    )

    db.add(db_user)
    db.flush()
    for role_name in dict.fromkeys(user_in.roles):
        db.add(UserRole(user=db_user, role=_get_or_create_role(db, role_name)))
    db.commit()
    db.refresh(db_user)
    db.refresh(db_user, attribute_names=["user_roles"])

    return _user_to_schema(db_user)


@router.get("/me", response_model=UserOut)
def read_current_user(
    current_user: User = Depends(get_current_active_user),
):
    return _user_to_schema(current_user)
